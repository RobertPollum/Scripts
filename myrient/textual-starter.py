from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Button, Label, DirectoryTree, Header, Footer
from textual.css.query import NoMatches
import httplib2, os, time, progressbar
import urllib.request
from bs4 import BeautifulSoup, SoupStrainer
from myrientsettings import Settings 

class MyrientNavigator(App):
    BINDINGS = [("d", "toggle_dark", "Toggle dark mode")]
    CSS_PATH="textual-starter.tcss"
    settings = Settings()
    text = "Original Text"
    http = httplib2.Http()
    links=[]

    def compose(self) -> ComposeResult:
        with Container(id="myrient-downloader", name="Myrient Downloader"):
            yield Header(name="Myriend Downloader", show_clock=True)
            yield Button("Press Me", id="request", variant="primary")
            yield Button("Don't Press Me", id="anti-test", variant="default")
            yield Label(self.text, id="label")
            yield DirectoryTree(path="./", classes=("invisible"))
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
        response, content = self.http.request(self.settings.base_url)

        self.text = content
        print("New text: ", self.text)
        self.query_one(Label).update(f"{self.text}")
        

    @on(Button.Pressed, "#anti-test")
    def anti_test_pressed(self, event: Button.Pressed) -> None:
        self.text = "anti test button pressed"
        print("New text: ", self.text)
        self.query_one(Label).update(f"{self.text}")

if __name__ == "__main__":
    MyrientNavigator().run(inline=False)