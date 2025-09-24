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
from MyrientSettingsScreen import MyrientSettingsScreen
from RequestParser import RequestParser

class MyrientNavigator(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH="MyrientNavigator.tcss"
    settings = Settings()
    text = "Original Text"
    http = httplib2.Http()
    request_parser = RequestParser()
    menu_container = None
    settings_screen = None

    def compose(self) -> ComposeResult:
        self.menu_container = Menu(id="menu", settings=self.settings)
        self.settings_screen = MyrientSettingsScreen(settings=self.settings, id="settings-screen")
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
                    yield self.settings_screen
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
        

    def update_settings_from_screen(self) -> None:
        """Update the main settings from the settings screen."""
        if hasattr(self, 'settings_screen'):
            self.settings = self.settings_screen.get_settings()
            if hasattr(self, 'menu_container') and self.menu_container:
                self.menu_container.update_settings(self.settings)
    
    @on(Button.Pressed, "#save-settings-btn")
    def on_settings_saved(self, event: Button.Pressed) -> None:
        """Handle when settings are saved from the settings screen."""
        self.update_settings_from_screen()
    
    @on(Button.Pressed, ".menu-button")
    def menu_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if(button_id != "show-settings"):
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

    def generate_menu_links(self) -> None:
        """
        Generate menu links by fetching and parsing a URL for anchor tags.
        This method uses the RequestParser to fetch links from a configured URL.
        """
        try:
            # Example URL - you may want to make this configurable in settings
            base_url = "https://myrient.erista.me/"  # Replace with actual Myrient URL
            
            # Fetch anchor tags from the URL
            anchors = self.request_parser.get_anchors_from_url(base_url)
            
            # Filter for relevant links (you can customize this filtering)
            filtered_anchors = self.request_parser.filter_anchors(
                anchors, 
                has_href=True
            )
            
            # Convert to absolute URLs
            absolute_anchors = self.request_parser.get_absolute_urls(filtered_anchors, base_url)
            
            # Update the menu container with the new links
            if self.menu_container and hasattr(self.menu_container, 'update_menu_links'):
                self.menu_container.update_menu_links(absolute_anchors)
            
            # Update UI to show success
            self.query_one("#menu-content-label").update(f"Loaded {len(absolute_anchors)} menu links")
            
        except Exception as e:
            error_msg = f"Error generating menu links: {str(e)}"
            print(error_msg)
            self.query_one("#menu-content-label").update(error_msg)

if __name__ == "__main__":
    navigator = MyrientNavigator()
    navigator.run(inline=False)