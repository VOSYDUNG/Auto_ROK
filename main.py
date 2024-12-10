import Mouse_key
import Avatar
import pyautogui
import time
import numpy as np
import math
import random
gold_pit=(1230,860,1230,760)
stone_pit=(1090,850,1090,760)
wood_pit=(960,850,960,760)
corn_pit=(830,860,830,760)
Log_yes=(1080,660)
Territory = 900,540,1260,750
done_characters = []



def Get_near_mark(list,Position_mark):
    min_distance = float('inf')
    nearest_point = None
    for coord in list:
        print('cord',coord)
        x, y = coord
        print(x)
        print(y)
        distance = math.sqrt((int(x) - int(Position_mark[0])) ** 2 + (int(y) - int(Position_mark[1])) ** 2)
        if distance < min_distance:
            min_distance = distance
            nearest_point = coord
    done_characters.append(nearest_point)



Daily= Mouse_key.Daily_farm()


# change account
Daily.change_account()
list_character,charimage = Avatar.All_star_character()
Position_mark = Avatar.detect_green_checkmark()

Get_near_mark(list_character,Position_mark)
print("Done characters",done_characters)
pyautogui.hotkey('ESC')
pyautogui.hotkey('ESC')
pyautogui.hotkey('o')
time.sleep(1)
x,y=Avatar.Territory_position(Territory)

Daily.Get_rss_clan(x,y)
Daily.Find_pit(corn_pit)
time.sleep(1.5)
Daily.Find_pit(corn_pit)
time.sleep(1.5)
Daily.Find_pit(wood_pit)
time.sleep(1.5)
Daily.Find_pit(wood_pit)
time.sleep(1.5)
Daily.Find_pit(stone_pit)
time.sleep(1.5)

Daily.change_account()

for next in list_character:
    if next not in done_characters:
        pyautogui.leftClick(next[0]+ Mouse_key.RandomValue(),next[1]+ Mouse_key.RandomValue(),duration=1)
        pyautogui.leftClick(Log_yes[0] + Mouse_key.RandomValue(),Log_yes[1]+ Mouse_key.RandomValue())
        time.sleep(30)
        x,y=Avatar.Territory_position(Territory)
        Daily.Get_rss_clan(x+Mouse_key.RandomValue(),y+Mouse_key.RandomValue())
        Daily.Find_pit(corn_pit)
        time.sleep(1.5)
        Daily.Find_pit(wood_pit)
        time.sleep(1.5)
        Daily.Find_pit(stone_pit)
        time.sleep(1.5)
        Daily.Find_pit(gold_pit)
        Daily.change_account()
        done_characters.append(next)
        print("Done characters",done_characters)
        





