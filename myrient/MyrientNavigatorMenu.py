from textual.app import App, ComposeResult, RenderResult
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button
import httplib2
from bs4 import BeautifulSoup
from MyrientSettings import Settings 
"""
Menu class is a container for the menu buttons
It will generate the menu buttons from the settings base_url and a settings button to open the settings
"""
class Menu(Horizontal):

    default_buttons = [
        Button("Settings", id="show-settings", variant="primary", classes="menu-button"),
    ]

    menu_buttons = []
    menu_links = []
    settings: Settings = Settings()
    # menu_container = None

    def __init__(self, id: str, settings: Settings):
        super().__init__( id=id)
        self.settings = settings
        http = httplib2.Http()
        response, content = http.request(self.settings.base_url)
        soup = BeautifulSoup(content, features="html.parser")
        
        # Find anchor tags with class "menu"
        menu_links = soup.find_all('a', class_='menu', href=True)
        menu_buttons = []
        for i, link in enumerate(menu_links):
            link_text = link.get_text(strip=True) or f"Menu Item {i}"
            link_href = link.get('href')
            button_id = f"menu-link-{i}"
            
            button = Button(
                link_text,
                id=button_id,
                variant="success",
                classes="menu-button"
            )
            menu_buttons.append(button)

        self.menu_buttons = menu_buttons
        self.menu_buttons.append(self.default_buttons[0])

    # def on_mount(self) -> None:
    #     do something when the menu is mounted

    # def render(self) -> RenderResult:
    #     render some inconsequential data

    def compose(self) -> ComposeResult:
        with Horizontal(id=f"{self.id}-container"):
            for button in self.menu_buttons:
                yield button

    def get_link(self, button_id: str) -> str:
        return self.menu_links[int(button_id.split("-")[-1])]

    def get_all_menu_links(self) -> list[str]:
        return self.menu_links