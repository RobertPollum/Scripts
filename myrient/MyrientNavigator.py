from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Label, DirectoryTree, Header, Footer, ContentSwitcher
from textual.css.query import NoMatches, WrongType
import httplib2, os, time, progressbar
import urllib.request
from bs4 import BeautifulSoup, SoupStrainer
from MyrientSettings import Settings 
from MyrientNavigatorMenu import Menu

class MyrientNavigator(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH="MyrientNavigator.tcss"
    settings = Settings()
    text = "Original Text"
    http = httplib2.Http()
    default_buttons = (
        Button("Base Menu", id="menu-button-0", variant="primary", classes="menu-button"),
        Button("Settings", id="menu-button-1", variant="primary", classes="menu-button")
    )
    menu_container = None

    def compose(self) -> ComposeResult:
        self.menu_container = Menu(id="menu", settings=self.settings)
        with Container(id="myrient-downloader", name="Myrient Downloader"):
            yield Header(name="Myriend Downloader", show_clock=True)
            # yield Menu("menu", self.settings)
            yield self.menu_container
            with ContentSwitcher(id="menu-content-switcher", initial="menu-content"):
                with Vertical(id="menu-content"):
                    yield Label("Home", id="home-label")
                    yield Button("Load Menu Links", id="request", variant="primary")
                with Vertical(id="menu-content-display"):
                    yield Label("Menu Content", id="menu-content-label")
                with Vertical(id="settings-container"):
                    yield Button("Save Settings", id="save-settings", variant="primary")
                    yield DirectoryTree(id="directory-tree", path=self.settings.download_directory)
            yield Footer()
           
    @on(Button.Pressed, "#show-settings")
    def show_settings(self, event: Button.Pressed) -> None:
        # settings_container = self.query_one("#settings-container")
        # settings_container.scroll_to_top()
        self.query_one("#menu-content-switcher").current = "settings-container"


    @on(Button.Pressed, "#request")
    def load_menu_links(self, event: Button.Pressed) -> None:
        #TODO get this button removed by getting the default load to work
        self.generate_menu_links()
        

    #TODO expand this function to save additional settings
    @on(Button.Pressed, "#save-settings")
    def save_settings(self, event: Button.Pressed) -> None:
        #TODO figure out additional settings that should be saved or editable
        #TODO figue out how to navigate to directories outside of the current directory
        self.settings.download_directory = self.query_one("#directory-tree", DirectoryTree).path
        self.settings.save()
        self.menu_container.update_settings(self.settings)
    
    @on(Button.Pressed, ".menu-button")
    def menu_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        self.query_one("#menu-content-switcher").current = "menu-content-display"
        self.query_one("#menu-content-label").update(f"{button_id}")
        #TODO diagnose why the label text isn't updating dynamically
        if button_id and button_id.startswith("menu-link-"):
            try:
                index = int(button_id.split("-")[-1])
                if 0 <= index < len(self.menu_container.get_all_menu_links()):
                    selected_link = self.menu_container.get_link(index)
                    link_href = selected_link.get('href')
                    link_text = selected_link.get_text(strip=True)
                    
                    label_text = f"Selected: {link_text} -> {link_href}"
                    print(f"Menu button pressed: {link_text} -> {link_href}")
                    self.query_one("#menu-content-label").update(label_text)
            except (ValueError, IndexError) as e:
                self.query_one("#menu-content-label").update(f"Error handling menu button press: {e}")

if __name__ == "__main__":
    navigator = MyrientNavigator()
    navigator.run(inline=False)