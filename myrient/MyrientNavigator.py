from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Button, Label, DirectoryTree, Header, Footer, ContentSwitcher
from textual.css.query import NoMatches, WrongType
import httplib2, os, time, progressbar
import urllib.request
from bs4 import BeautifulSoup, SoupStrainer
from MyrientSettings import Settings 

class MyrientNavigator(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH="MyrientNavigator.tcss"
    settings = Settings()
    text = "Original Text"
    http = httplib2.Http()
    links=[]
    menu_links = []
    menu_buttons = []

    def generate_menu_links(self):
        # response, content = self.http.request(self.settings.base_url)
        # soup = BeautifulSoup(content, features="html.parser")
        
        # # Find anchor tags with class "menu"
        # menu_links = soup.find_all('a', class_='menu', href=True)
        # self.menu_links = menu_links

        # for i, link in enumerate(menu_links):
        #     link_text = link.get_text(strip=True) or f"Menu Item {i+1}"
        #     link_href = link.get('href')
        #     button_id = f"menu-link-{i}"
        #     yield Button(link_text, id=button_id, variant="success", classes="menu-button")
        response, content = self.http.request(self.settings.base_url)
        soup = BeautifulSoup(content, features="html.parser")
        
        # Find anchor tags with class "menu"
        menu_links = soup.find_all('a', class_='menu', href=True)

        self.menu_links = menu_links
        self.menu_buttons = self.menu_buttons[0:1]
        
        # Clear existing dynamic buttons
        menu_container = self.query_one("#menu-buttons")
        # menu_container = self.query_one("#menu-content-switcher")
        menu_container.remove_children()
        
        # Create buttons for each menu link
        for i, link in enumerate(menu_links):
            link_text = link.get_text(strip=True) or f"Menu Item {i+1}"
            link_href = link.get('href')
            button_id = f"menu-link-{i + 1}"
            
            try:
                self.query_one(f"#{button_id}", Button) 
            except NoMatches:
                button = Button(
                    link_text,
                    id=button_id,
                    variant="success",
                    classes="menu-button"
                )
                self.menu_buttons.append(button)
                print("Button already exists")
        
        for button in self.menu_buttons:
            menu_container.mount(button)

        self.text = f"Found {len(menu_links)} menu links"
        print(f"Found {len(menu_links)} menu links: ", [link.get('href') for link in menu_links])
        self.query_one(Label).update(f"Found {menu_links[0]} menu links")
            


    def compose(self) -> ComposeResult:
        initial_button = Button("Base Menu", id="menu-button-0", variant="primary", classes="menu-button")
        self.menu_buttons.append(initial_button)
        with Container(id="myrient-downloader", name="Myrient Downloader"):
            yield Header(name="Myriend Downloader", show_clock=True)
            with Horizontal(id="menu-buttons"):
                yield initial_button
            with ContentSwitcher(id="menu-content-switcher", initial="menu-content"):
                with Vertical(id="menu-content"):
                    yield Button("Load Menu Links", id="request", variant="primary")
                    yield Button("Clear", id="anti-test", variant="default")
                    yield Label(self.text, id="label")
                with Vertical(id="settings-container"):
                    yield Button("Save Settings", id="save-settings", variant="primary")
                    yield DirectoryTree(id="directory-tree", path=self.settings.download_directory)
            yield Footer()

    def watch_data(self) -> None:
        self.query_one(Label).update(f"{self.text}")

    def on_key(self, event: events.Key) -> None:
        def press(button_id: str) -> None:
            """Press a button, should it exist."""
            try:
                self.query_one(f"#{button_id}", Button).press()
            except NoMatches:
                pass

        key = event.key
        
        # button_id = self.NAME_MAP.get(key)
        # if button_id is not None:
        #         press(self.NAME_MAP.get(key, key))

           

    @on(Button.Pressed, "#request")
    def test_pressed(self, event: Button.Pressed) -> None:
        #TODO get this button removed by getting the default load to work
        self.generate_menu_links()
        

    @on(Button.Pressed, "#save-settings")
    def save_settings(self, event: Button.Pressed) -> None:
        #TODO figure out additional settings that should be saved or editable
        self.settings.download_directory = self.query_one("#directory-tree", DirectoryTree).path
        self.settings.save()

    @on(Button.Pressed, "#anti-test")
    def clear_menu_links(self, event: Button.Pressed) -> None:
        # Clear dynamic buttons
        menu_container = self.query_one("#menu-buttons")
        menu_container.remove_children()
        self.menu_links = self.menu_links[0:1]
        self.menu_buttons = self.menu_buttons[0:1]
        menu_container.mount(self.menu_buttons[0])
        
        self.text = "Cleared menu links"
        print("New text: ", self.text)
        self.query_one(Label).update(f"{self.text}")
    
    @on(Button.Pressed, ".menu-button")
    def menu_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id and button_id.startswith("menu-link-"):
            try:
                index = int(button_id.split("-")[-1])
                if 0 <= index < len(self.menu_links):
                    selected_link = self.menu_links[index]
                    link_href = selected_link.get('href')
                    link_text = selected_link.get_text(strip=True)
                    
                    self.text = f"Selected: {link_text} -> {link_href}"
                    print(f"Menu button pressed: {link_text} -> {link_href}")
                    self.query_one(Label).update(f"Selected: {link_text}")
            except (ValueError, IndexError) as e:
                print(f"Error handling menu button press: {e}")

if __name__ == "__main__":
    navigator = MyrientNavigator()
    #TODO figure out how to auto generate the menu asynchronously on startup
    # navigator.generate_menu_links()
    navigator.run(inline=False)