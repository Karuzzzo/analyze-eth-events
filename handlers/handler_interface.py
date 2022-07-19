class handlerInterface:
    def name(self) -> str:
        """Returns name of this handler."""
        pass
    
    def event_signature(self) -> str:
        """Returns event signature this handler is associated with."""
        pass

    def handle_event(self, event):
        """processes submitted event."""
        pass

    def on_close(self):
        """closes everything, possibly saving data or something."""
        pass