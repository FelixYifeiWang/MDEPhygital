import tkinter as tk
from tkinter import Canvas


class GestureUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Gesture Detection UI")

        self.root.attributes("-fullscreen", True)
        self.root.configure(bg="black")

        self.canvas = Canvas(self.root, bg="#050508", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        self.build_ui()

        # Key listeners
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.focus_force()

        # Only mouse for close button
        self.canvas.bind("<Button-1>", self.on_click)

        # Keep layout centered
        self.root.bind("<Configure>", self.on_resize)

        self.root.mainloop()

    # ---------------- UI ---------------- #

    def build_ui(self):
        w = self.root.winfo_screenwidth()
        h = self.root.winfo_screenheight()
        self.canvas.delete("all")

        # Close button
        padding = 24
        btn_size = 40
        x2 = w - padding
        x1 = x2 - btn_size
        y1 = padding
        y2 = y1 + btn_size

        self.exit_rect = self.canvas.create_oval(
            x1, y1, x2, y2,
            fill="#22252A", outline="#555A60", width=1.5
        )
        self.exit_text = self.canvas.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text="×",
            fill="#F5F5F7",
            font=("Helvetica", 18, "bold")
        )

        # Center card
        card_w = 420
        card_h = 260
        self.card_x1 = (w - card_w) / 2
        self.card_y1 = (h - card_h) / 2
        self.card_x2 = self.card_x1 + card_w
        self.card_y2 = self.card_y1 + card_h

        self.card_rect = self.canvas.create_rectangle(
            self.card_x1, self.card_y1, self.card_x2, self.card_y2,
            fill="#15171C", outline="#3A3D45", width=1.5
        )

        # Gesture number (center)
        self.number_text = self.canvas.create_text(
            w / 2,
            h / 2 - 20,
            text="–",
            fill="#FFFFFF",
            font=("Helvetica", 80, "bold")
        )

        # Subtitle
        self.subtitle_text = self.canvas.create_text(
            w / 2,
            h / 2 + 40,
            text="Waiting for gesture (1–7)",
            fill="#8E8E93",
            font=("Helvetica", 18)
        )

        # Helper text at bottom
        self.helper_text = self.canvas.create_text(
            w / 2,
            h - 60,
            text="Press 1–7 to show a gesture ID • Release key to clear • Esc/Q to exit",
            fill="#636366",
            font=("Helvetica", 14)
        )

    # ---------------- EVENTS ---------------- #

    def on_resize(self, event):
        if event.widget == self.root:
            self.build_ui()

    def on_click(self, event):
        x, y = event.x, event.y
        if self.is_inside(x, y, self.exit_rect):
            self.root.destroy()

    # Key Press → show number
    def on_key_press(self, event):
        if event.keysym == "Escape" or event.char.lower() == "q":
            self.root.destroy()
            return

        if event.char in "1234567":
            self.show_number(event.char)

    # Key Release → hide number
    def on_key_release(self, event):
        if event.char in "1234567":
            self.clear_number()

    # ---------------- UI UPDATES ---------------- #

    def show_number(self, number):
        self.canvas.itemconfig(self.number_text, text=str(number))
        self.canvas.itemconfig(
            self.subtitle_text, text=f"Detected gesture ID: {number}"
        )
        print(f"Gesture detected: {number}")

    def clear_number(self):
        self.canvas.itemconfig(self.number_text, text="–")
        self.canvas.itemconfig(
            self.subtitle_text, text="Waiting for gesture (1–7)"
        )

    # ---------------- UTIL ---------------- #

    def is_inside(self, x, y, shape_id):
        x1, y1, x2, y2 = self.canvas.coords(shape_id)
        return x1 <= x <= x2 and y1 <= y <= y2


if __name__ == "__main__":
    GestureUI()
