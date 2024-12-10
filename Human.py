from pynput import mouse, keyboard
import time

# Tạo file log và ghi header
log_file = "log.txt"
with open(log_file, "w") as f:
    f.write("Time\t\t\t\tEvent\t\tDetails\n")
    f.write("-----------------------------------------------------------\n")

# Ghi sự kiện chuột vào file log
def on_click(x, y, button, pressed):
    with open(log_file, "a") as f:
        if pressed:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tMouse Clicked\t{button} at ({x}, {y})\n")
        else:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tMouse Released\t{button} at ({x}, {y})\n")

def on_move(x, y):
    with open(log_file, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tMouse Moved\tto ({x}, {y})\n")

def on_scroll(x, y, dx, dy):
    with open(log_file, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tMouse Scrolled\tat ({x}, {y})\n")

# Ghi sự kiện bàn phím vào file log
def on_press(key):
    with open(log_file, "a") as f:
        try:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tKey Pressed\t{key.char}\n")
        except AttributeError:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tSpecial Key Pressed\t{key}\n")

def on_release(key):
    with open(log_file, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tKey Released\t{key}\n")
    # Thoát khi nhấn phím Esc
    if key == keyboard.Key.esc:
        return False

# Chạy cả listener chuột và bàn phím
def start_logging():
    with mouse.Listener(on_click=on_click, on_move=on_move, on_scroll=on_scroll) as mouse_listener, \
         keyboard.Listener(on_press=on_press, on_release=on_release) as keyboard_listener:
        mouse_listener.join()
        keyboard_listener.join()

if __name__ == "__main__":
    start_logging()
