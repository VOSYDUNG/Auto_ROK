import pyautogui
import cv2
import numpy as np
import time
import torch
import easyocr


lower_white = np.array([0, 0, 180])   
upper_white = np.array([180, 50, 255])
lower_blue = np.array([80, 100, 100])   
upper_blue = np.array([100, 255, 255])

reader = easyocr.Reader(['en'])
x1, y1 = 650, 330
x2, y2 = 1400, 810
Territory = 900,540,1260,750
character_star = y2-y1

def detect_green_checkmark():
    # Đọc ảnh
    x_mark , y_mark = None,None
    screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    image = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
    # Chuyển đổi sang không gian màu HSV
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # cv2.imshow("Detected Green Checkmark", hsv)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    
    # Định nghĩa khoảng màu xanh lá trong không gian màu HSV
    lower_green = np.array([50, 110, 50])
    upper_green = np.array([80, 255, 255])

    # rgb(38,223,53) tich
    # rgb(75,104,34) avatar
    
    # Tạo mặt nạ cho vùng màu xanh lá
    mask = cv2.inRange(hsv, lower_green, upper_green)
    # cv2.imshow("Detected Green Checkmark", mask)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    # Áp dụng phép toán làm mịn để giảm nhiễu
    mask = cv2.medianBlur(mask, 13)
    # cv2.imshow("Detected Green Checkmark", mask)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    # Tìm các đường viền trong mặt nạ
    contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    for contour in contours:
        # Xấp xỉ đa giác cho mỗi đường viền
        
        cv2.polylines(image, [contour], isClosed=True, color=(255, 0, 0), thickness=2)
        M = cv2.moments(contour)
        
        if M["m00"] != 0:
            # Tính toán tọa độ tâm của contour
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            # Vẽ một chấm tròn tại tâm của contour
            cv2.circle(image, (cx, cy), 5, (0, 0, 255), -1)
            # In ra tọa độ tâm
            x_mark, y_mark = cx+x1,cy+y1
            
        image = np.array(image)
    
    # Hiển thị kết quả

    # cv2.imshow("Detected Green Checkmark", image)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    return x_mark , y_mark

def Territory_position(Possition):
    time.sleep(1)
    pyautogui.leftClick(960,560,duration=1)
    pyautogui.hotkey('o')
    time.sleep(1)
    screenshot = pyautogui.screenshot(region=(Possition[0], Possition[1], Possition[2] - Possition[0], Possition[3]-Possition[1]))
    image = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
    results = reader.readtext(image)
    x,y=None,None
    Flag = []
    
    print(results)
    for result in results:
        bounding_box, text, confidence = result
        if 'territory'  in text.lower():
            Flag.append((bounding_box, text, confidence))
            pts = np.array(bounding_box, np.int32)
            pts = pts.reshape((-1, 1, 2))
            print(bounding_box)
            x,y=Possition[0] +bounding_box[0][0] +(bounding_box[1][0]-bounding_box[0][0])/2 ,Possition[1]+bounding_box[3][1]/2

            pyautogui.leftClick(Possition[0] +bounding_box[0][0] +(bounding_box[1][0]-bounding_box[0][0])/2 ,Possition[1]+bounding_box[3][1]/2,duration=0.7)
            cv2.polylines(image, [pts], isClosed=True, color=(255, 0, 0), thickness=2)
            # Hiển thị text
            cv2.putText(image, f'{text} ', (bounding_box[0][0], bounding_box[0][1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
            
    return x,y


def All_star_character():
    time.sleep(1)
    screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    # detect_green_checkmark(np.array(screenshot))
    image = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
    character_star = y2-y1
    star_characters = []
    normal_characters = []
    results = reader.readtext(image)

    for result in results:
        bounding_box, text, confidence = result
        if 'star characters'  in text.lower():
            star_characters.append((bounding_box, text, confidence))
            pts = np.array(bounding_box, np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.polylines(image, [pts], isClosed=True, color=(255, 0, 0), thickness=2)
        
            # Hiển thị text
            cv2.putText(image, f'{text} ', (bounding_box[0][0], bounding_box[0][1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
        elif 'normal characters' in text.lower():
            normal_characters.append((bounding_box, text, confidence))
            # print(bounding_box)
            #box = bounding_box[0]
            character_star = bounding_box[0][1]
            # print(character_star)
            pts = np.array(bounding_box, np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.polylines(image, [pts], isClosed=True, color=(255, 0, 0), thickness=2)
        
            # Hiển thị text
            cv2.putText(image, f'{text} ', (bounding_box[0][0], bounding_box[0][1] - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)  




    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (9, 9), 0)
    circles = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, 1, 20, param1=50, param2=30, minRadius=20, maxRadius=50)
    list_character = []
    # Kiểm tra và đếm số lượng hình tròn
    num_characters = 0
    
    if circles is not None:
        circles = np.uint16(np.around(circles))
        # Vẽ hình tròn lên ảnh để kiểm tra
        for i in circles[0, :]:
            if i[1] < character_star :
                num_characters +=1
                cv2.circle(image, (i[0], i[1]), i[2], (0, 255, 0), 2)
                cv2.circle(image, (i[0], i[1]), 2, (0, 0, 255), 3)
                character_click = (i[0]+x1,i[1]+y1)
                list_character.append(character_click)


    # Hiển thị ảnh đã xử lý (tuỳ chọn)
    # cv2.imshow("Processed Image", image)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()
    print(list_character)

    print(f"Số lượng nhân vật: {num_characters}")
    return list_character,image
def detect_white_lines():
    # Take a screenshot and convert it to a format suitable for OpenCV
    x1, y1 = 650, 330
    x2, y2 = 1400, 810
    screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    image = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
    
    # Convert the image to the HSV color space
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    
    # Define the green color range for masking
    lower_white = np.array([0, 0, 180])   # Low saturation, high value
    upper_white = np.array([180, 50, 255])
    #mask = cv2.inRange(hsv, lower_white, upper_white)
    mask = cv2.inRange(hsv, lower_blue, upper_blue)
    
    # Apply Canny edge detection for clearer line detection
    edges = cv2.Canny(mask, 50, 150, apertureSize=3)
    
    # Use the Hough Line Transform to detect lines
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi/180, threshold=100, minLineLength=100, maxLineGap=10)
    
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            # Draw each line in blue on the image
            cv2.line(image, (x1, y1), (x2, y2), (255, 0, 0), 2)
            print(f"Line from ({x1}, {y1}) to ({x2}, {y2})")

    # Display the image with detected lines
    cv2.imshow("Detected Green Lines", image)
    
    # Exit condition: Press 'q' to close the display window
    if cv2.waitKey(1) & 0xFF == ord("q"):
        cv2.destroyAllWindows()

def detect_green_lines():
    # Take a screenshot and convert it to a format suitable for OpenCV
    x1, y1 = 650, 330
    x2, y2 = 1400, 810
    screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
    image = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
    
    # Convert the image to the HSV color space
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    
    # Define the green color range for masking
    lower_green = np.array([50, 110, 50])
    upper_green = np.array([80, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)
    
    # Apply Canny edge detection for clearer line detection
    edges = cv2.Canny(mask, 30, 100, apertureSize=5)
    
    # Use the Hough Line Transform to detect lines
    lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi/180, threshold=100, minLineLength=100, maxLineGap=10)
    
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            # Draw each line in blue on the image
            cv2.line(image, (x1, y1), (x2, y2), (255, 0, 0), 2)
            print(f"Line from ({x1}, {y1}) to ({x2}, {y2})")

    # Display the image with detected lines
    cv2.imshow("Detected Green Lines", image)
    
    # Exit condition: Press 'q' to close the display window
    if cv2.waitKey(1) & 0xFF == ord("q"):
        cv2.destroyAllWindows()

# All_star_character()
def StreamScreen():
    while True:
        try:
            detect_white_lines()
            # Chụp màn hình trong vùng xác định
            # screenshot = pyautogui.screenshot(region=(x1, y1, x2 - x1, y2 - y1))
            # image = cv2.cvtColor(np.asarray(screenshot), cv2.COLOR_RGB2BGR)
            
            # # Chuyển đổi ảnh sang không gian màu HSV
            # hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            
            # # Đặt ngưỡng màu xanh lá
            # lower_green = np.array([10, 100, 20])
            # upper_green = np.array([20, 255, 200])
            # mask = cv2.inRange(hsv, lower_green, upper_green)
            
            # # Tìm các đường viền của màu xanh lá trong vùng màn hình
            # contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            # for contour in contours:
            #     # Vẽ các đường viền trên ảnh
            #     cv2.polylines(image, [contour], isClosed=True, color=(255, 0, 0), thickness=2)
                
            #     # Tính toán tâm của contour nếu diện tích khác 0
            #     M = cv2.moments(contour)
            #     if M["m00"] != 0:
            #         cx = int(M["m10"] / M["m00"])
            #         cy = int(M["m01"] / M["m00"])
                    
            #         # Vẽ chấm đỏ tại tâm và in tọa độ
            #         cv2.circle(image, (cx, cy), 5, (0, 0, 255), -1)
            #         x_mark, y_mark = cx + x1, cy + y1
            #         print(f"Tâm tại tọa độ: ({x_mark}, {y_mark})")
            
            # # Hiển thị ảnh với contour
            # cv2.imshow("Detected Green Checkmark", image)
            
            # # Điều kiện thoát: nhấn phím 'q'
            # if cv2.waitKey(1) & 0xFF == ord("q"):
            #     break
        
        except Exception as e:
            print("Đã xảy ra lỗi:", e)
            break  # Thoát vòng lặp nếu xảy ra lỗi

    cv2.destroyAllWindows()