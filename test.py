import pyautogui
import time

# Hàm để ghi lại tọa độ và thời gian di chuyển của chuột
def ghi_toa_do_chuot(thoi_gian_ghi):
    toa_do_va_thoi_gian = []
    start_time = time.time()
    last_time = start_time
    
    while True:
        # Lấy tọa độ hiện tại của chuột
        x, y = pyautogui.position()
        current_time = time.time()
        duration = current_time - last_time
        toa_do_va_thoi_gian.append((x, y, duration))
        
        last_time = current_time
        
        # Dừng lại sau thời gian ghi nhất định
        if current_time - start_time > thoi_gian_ghi:
            break
        
        time.sleep(0.1)
    
    return toa_do_va_thoi_gian

# Hàm để thực hiện lại thao tác đã ghi
def thuc_hien_lai_thao_tac(toa_do_va_thoi_gian):
    for x, y, duration in toa_do_va_thoi_gian:
        pyautogui.moveTo(x, y, duration=duration)

# Ghi lại tọa độ và thời gian chuột trong 5 giây
print("write position")
toa_do_va_thoi_gian_chuot = ghi_toa_do_chuot(5)

# Thực hiện lại thao tác đã ghi
time.sleep(2)  # Dừng lại 2 giây trước khi thực hiện lại
print("do again")
thuc_hien_lai_thao_tac(toa_do_va_thoi_gian_chuot)