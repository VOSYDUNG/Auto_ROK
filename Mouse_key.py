import pyautogui
import random
import time
print(pyautogui.size()) #
march=(1160,750)
pit_click = (960,560)
gather_click = (1180,640)
new_troop= (1400,400)
setting_click = (642,817)
character_click = (515,630)
Avatar_click = ()
def RandomValue():
    return int(random.randint(-10,10))

class Daily_farm:
    def __init__(self):
        pass
    def Find_pit(self,pit_position):
        pyautogui.hotkey('F')
        pyautogui.leftClick(pit_position[0]  + RandomValue() ,pit_position[1] + RandomValue(),duration=0.7)
        pyautogui.leftClick(pit_position[2] + RandomValue() ,pit_position[3]+ RandomValue(),duration=0.7)
        time.sleep(1)
        pyautogui.leftClick(pit_click[0] + RandomValue(),pit_click[1] + RandomValue(),duration=0.5)
        pyautogui.leftClick(gather_click[0] + RandomValue(),gather_click[1] + RandomValue(),duration=0.5)
        pyautogui.leftClick(new_troop[0]+RandomValue(),new_troop[1]+RandomValue(),duration=0.5)
        pyautogui.leftClick(march[0]+RandomValue(),march[1]+RandomValue(),duration=0.5)
    def Get_rss_clan(self,x,y):
        pyautogui.leftClick(x+RandomValue(),y+RandomValue(),duration=0.7)
        pyautogui.leftClick(1220+RandomValue(),400+RandomValue(),duration=0.2)
        pyautogui.hotkey('ESC')
        time.sleep(0.5)
        pyautogui.hotkey('ESC')
        time.sleep(0.5)
        pyautogui.hotkey('space')
    def change_account(self):
        time.sleep(1)
        pyautogui.hotkey('ESC')
        pyautogui.leftClick(setting_click[0]+RandomValue(),setting_click[1]+RandomValue(),duration=0.7)
        pyautogui.leftClick(character_click[0]+RandomValue(),character_click[1]+RandomValue(),duration=0.7)
        pyautogui.moveTo(980,550,duration=0.7)
        time.sleep(0.1)
        pyautogui.scroll(-110)
        time.sleep(0.1)
        pyautogui.scroll(-110)
        time.sleep(0.1)
        pyautogui.scroll(-110)
        time.sleep(0.1)
        pyautogui.scroll(-110)
        pyautogui.moveTo(450,600,duration=0.7)
    def Get_vip(self):
        pyautogui.hotkey('v')





    















