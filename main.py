import flet as ft
import qrcode
import base64
import json
import requests
import threading
import time
from io import BytesIO

BASE_URL = "https://api.yessgo.org/api/v1"


class PartnerTerminal:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "Yess!Go POS"
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.window_width = 420
        self.page.window_height = 850
        self.page.scroll = ft.ScrollMode.AUTO

        self.partner_id = None
        self.partner_name = ""
        self.basket = {}
        self.is_polling = False

        self.catalog_list = ft.Column(spacing=10)
        self.qr_img = ft.Image(src_base64="", width=250, height=250, visible=False)
        self.total_som_text = ft.Text("К оплате: 0 сом", size=18, weight="w500")
        self.total_coin_text = ft.Text("Списание: 0 YC", size=24, weight="bold", color="orange700")
        self.status_label = ft.Text("Соберите заказ", size=14, color="grey")
        self.loading = ft.ProgressBar(visible=False)

        self.show_login_screen()

    def show_login_screen(self):
        self.page.clean()
        self.id_input = ft.TextField(label="ID Партнёра", value="10")
        self.name_input = ft.TextField(label="Название заведения", value="Yess!Go Store")
        self.page.add(
            ft.Container(
                content=ft.Column([
                    ft.Icon(name="stars", size=70, color="orange700"),
                    ft.Text("Yess!Go Coin Terminal", size=24, weight="bold"),
                    self.id_input, self.name_input,
                    ft.ElevatedButton("Войти", width=400, on_click=self.handle_login)
                ], horizontal_alignment="center"),
                padding=40, margin=ft.margin.only(top=100)
            )
        )

    def handle_login(self, e):
        try:
            res = requests.get(f"{BASE_URL}/partners/{self.id_input.value}/products", timeout=5)
            if res.status_code == 200:
                self.partner_id = int(self.id_input.value)
                self.partner_name = self.name_input.value
                self.init_terminal_ui()
        except:
            pass

    def init_terminal_ui(self):
        self.page.clean()
        self.page.appbar = ft.AppBar(
            title=ft.Text(f"{self.partner_name} (ID: {self.partner_id})"),
            bgcolor="orange50",
            actions=[ft.IconButton("logout", on_click=lambda _: self.show_login_screen())]
        )
        self.page.add(
            ft.Container(
                padding=20,
                content=ft.Column([
                    ft.Row([
                        ft.Text("Меню", size=20, weight="bold"),
                        ft.TextButton("Очистить", icon="delete", on_click=self.clear_basket)
                    ], alignment="spaceBetween"),
                    self.loading,
                    self.catalog_list,
                    ft.Divider(),
                    self.total_som_text,
                    self.total_coin_text,
                    self.status_label,
                    ft.ElevatedButton(
                        "Генерировать QR на списание YC",
                        icon="qr_code", width=400, height=60,
                        on_click=self.generate_qr
                    ),
                    ft.Column([self.qr_img], key="qr_section", horizontal_alignment="center")
                ])
            )
        )
        self.load_catalog()

    def load_catalog(self):
        self.loading.visible = True
        self.page.update()
        try:
            products = requests.get(f"{BASE_URL}/partners/{self.partner_id}/products").json().get("items", [])
            self.catalog_list.controls.clear()
            for p in products:
                pid = p['id']
                # Считаем коины: разница между оригинальной ценой и текущей
                # Если скидки нет, коин = 0
                coin_value = max(0, p.get('original_price', 0) - p.get('price', 0))

                in_basket = pid in self.basket
                self.catalog_list.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Column([
                                ft.Text(p['name'], weight="bold"),
                                ft.Row([
                                    ft.Text(f"{p['price']} сом", size=12, color="blue"),
                                    ft.Text(f"| {int(coin_value)} YC", size=12, color="orange700", weight="bold"),
                                ])
                            ], expand=True),
                            ft.Row([
                                ft.IconButton("remove", on_click=lambda e, p=p: self.update_basket(p, -1)),
                                ft.Text(str(self.basket[pid]['qty']) if in_basket else "0"),
                                ft.IconButton("add", on_click=lambda e, p=p: self.update_basket(p, 1)),
                            ])
                        ]),
                        padding=10, border=ft.border.all(1, "orange200" if in_basket else "outlineVariant"),
                        bgcolor="orange50" if in_basket else None, border_radius=10
                    )
                )
        except:
            pass
        self.loading.visible = False
        self.page.update()

    def update_basket(self, product, delta):
        pid = product['id']
        if pid not in self.basket and delta > 0:
            # Сохраняем и цену и разницу (коины)
            coin = max(0, product.get('original_price', 0) - product.get('price', 0))
            self.basket[pid] = {"price": product['price'], "coin": coin, "qty": 0}

        if pid in self.basket:
            self.basket[pid]["qty"] += delta
            if self.basket[pid]["qty"] <= 0: del self.basket[pid]

        self.refresh_ui()

    def clear_basket(self, e):
        self.basket.clear()
        self.refresh_ui()

    def refresh_ui(self):
        total_som = sum(v["price"] * v["qty"] for v in self.basket.values())
        total_coin = sum(v["coin"] * v["qty"] for v in self.basket.values())

        self.total_som_text.value = f"К оплате (сомы): {total_som} сом"
        self.total_coin_text.value = f"Списание коинов: {int(total_coin)} YC"
        self.load_catalog()

    def generate_qr(self, e):
        if not self.basket: return
        # JSON содержит только ID и Кол-во. Сервер сам найдет original_price и price.
        order_data = {
            "partnerId": self.partner_id,
            "paymentMethod": "yescoin",
            "items": [{"productId": pid, "quantity": item["qty"]} for pid, item in self.basket.items()]
        }
        qr_json = json.dumps(order_data)
        qr = qrcode.QRCode(box_size=10, border=2)
        qr.add_data(qr_json)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        buff = BytesIO()
        img.save(buff, format="PNG")
        self.qr_img.src_base64 = base64.b64encode(buff.getvalue()).decode()
        self.qr_img.visible = True
        self.status_label.value = "Клиент должен отсканировать QR для списания YC"
        self.page.update()
        self.page.scroll_to(key="qr_section", duration=500)


if __name__ == "__main__":
    ft.app(target=lambda page: PartnerTerminal(page))