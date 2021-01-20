"""
"""

# pylint: disable=import-error
import gc
import time
import math
import json
import board
import busio
import displayio
from digitalio import DigitalInOut, Pull
from adafruit_debouncer import Debouncer
from rtc import RTC
from adafruit_matrixportal.network import Network
from adafruit_matrixportal.matrix import Matrix
from adafruit_bitmap_font import bitmap_font
import adafruit_display_text.label
import adafruit_lis3dh

try:
    from secrets import secrets
except ImportError:
    print('WiFi secrets are kept in secrets.py, please add them there!')
    raise

# CONFIGURABLE SETTINGS ----------------------------------------------------

# If set, use 12-hour time vs 24-hour (e.g. 3:00 vs 15:00)
TWELVE_HOUR = True
COUNTDOWN = False  # If set, show time to (vs time of) next rise/set event
BITPLANES = 6      # Ideally 6, but can set lower if RAM is tight
MODE = 0           # I'm calling mode 0 = default with moon, mode 1 = screen showing the title of the meeting.
MEETINGTITLE = ""  # This will hold the text for the next meeting.
nxtEventInt = 0    # global var for next event
nxtEventEnd = 0
nxtEventTitle = "Why Doesn't This Work?"
nxtEventTitleWidth = 0

currentTitleX = 65
allDay = False
frameCounter = 0
SPRITESPEED = 5
BACKGROUND = 'moon/splash-1.bmp'
titlePosition = 0

LAYER_BACKGROUND = 0
LAYER_NOWDATE = 1
LAYER_NOWTIME = 2
LAYER_EVENTDATE = 3
LAYER_EVENTTITLE = 4



# SET UP BUTTONS

pin_down = DigitalInOut(board.A1)
pin_down.switch_to_input(pull=Pull.UP)
button_down = Debouncer(pin_down)

try:
    pin_up = DigitalInOut(board.A4)
except:
    time.sleep(5)
    pin_up = DigitalInOut(board.A4)

pin_up.switch_to_input(pull=Pull.UP)
button_up = Debouncer(pin_up)

# SOME UTILITY FUNCTIONS AND CLASSES ---------------------------------------

def parse_time(timestring, is_dst=-1):
    """ Given a string of the format YYYY-MM-DDTHH:MM:SS.SS-HH:MM (and
        optionally a DST flag), convert to and return an equivalent
        time.struct_time (strptime() isn't available here). Calling function
        can use time.mktime() on result if epoch seconds is needed instead.
        Time string is assumed local time; UTC offset is ignored. If seconds
        value includes a decimal fraction it's ignored.
    """
    date_time = timestring.split('T')         # Separate into date and time
    year_month_day = date_time[0].split('-')  # Separate time into Y/M/D
    hour_minute_second = date_time[1].split('+')[0].split('-')[0].split(':')
    return time.struct_time(int(year_month_day[0]),
                            int(year_month_day[1]),
                            int(year_month_day[2]),
                            int(hour_minute_second[0]),
                            int(hour_minute_second[1]),
                            int(hour_minute_second[2].split('.')[0]),
                            -1, -1, is_dst)


def update_time(timezone=None):
    """ Update system date/time from WorldTimeAPI public server;
        no account required. Pass in time zone string
        (http://worldtimeapi.org/api/timezone for list)
        or None to use IP geolocation. Returns current local time as a
        time.struct_time and UTC offset as string. This may throw an
        exception on fetch_data() - it is NOT CAUGHT HERE, should be
        handled in the calling code because different behaviors may be
        needed in different situations (e.g. reschedule for later).
    """

    print('getting time from octoprint server instead')
    time_url = 'http://192.168.1.242:8099/time.php'

    print('updating time data with time url :')
    print(time_url)
    for _ in range(5): # Retries - This seems to work finally.
        try:
            time_data = NETWORK.fetch_data(time_url,
                                            json_path=[['datetime'],
                                            ['dst'], ['utc_offset']])
            time_struct = parse_time(time_data[0], time_data[1])
            RTC().datetime = time_struct
            return time_struct, time_data[2]

        except Exception as e:
            print('shit didn\'t work')
            print(e)
            print(time_data)

def hh_mm(time_struct):
    """ Given a time.struct_time, return a string as H:MM or HH:MM, either
        12- or 24-hour style depending on global TWELVE_HOUR setting.
        This is ONLY for 'clock time,' NOT for countdown time, which is
        handled separately in the one spot where it's needed.
    """
    if TWELVE_HOUR:
        if time_struct.tm_hour > 12:
            hour_string = str(time_struct.tm_hour - 12) # 13-23 -> 1-11 (pm)
        elif time_struct.tm_hour > 0:
            hour_string = str(time_struct.tm_hour) # 1-12
        else:
            hour_string = '12' # 0 -> 12 (am)
    else:
        hour_string = '{0:0>2}'.format(time_struct.tm_hour)
    return hour_string + ':' + '{0:0>2}'.format(time_struct.tm_min)

# ONE-TIME INITIALIZATION --------------------------------------------------

MATRIX = Matrix(bit_depth=BITPLANES)
DISPLAY = MATRIX.display
ACCEL = adafruit_lis3dh.LIS3DH_I2C(busio.I2C(board.SCL, board.SDA),
                                   address=0x19)
_ = ACCEL.acceleration # Dummy reading to blow out any startup residue
time.sleep(0.1)
DISPLAY.rotation = (int(((math.atan2(-ACCEL.acceleration.y,
                                     -ACCEL.acceleration.x) + math.pi) /
                         (math.pi * 2) + 0.875) * 4) % 4) * 90

LARGE_FONT = bitmap_font.load_font('/fonts/helvB12.bdf')
SMALL_FONT = bitmap_font.load_font('/fonts/helvR10.bdf')
SYMBOL_FONT = bitmap_font.load_font('/fonts/6x10.bdf')
LARGE_FONT.load_glyphs('0123456789:')
SMALL_FONT.load_glyphs('0123456789:/.%')

# Display group is set up once, then we just shuffle items around later.
# Order of creation here determines their stacking order.
GROUP = displayio.Group(max_size=15)

# This is where the original code set up the background.
# Element 0 is the splash and background
try:
    FILENAME = 'moon/splash-0.bmp'
    BITMAP = displayio.OnDiskBitmap(open(FILENAME, 'rb'))
    TILE_GRID = displayio.TileGrid(BITMAP,
                                   pixel_shader=displayio.ColorConverter(),)
    GROUP.append(TILE_GRID)
except:
    GROUP.append(adafruit_display_text.label.Label(SMALL_FONT, color=0xFF0000,
                                                   text='AWOO'))
    GROUP[0].x = (DISPLAY.width - GROUP[0].bounding_box[2] + 1) // 2
    GROUP[0].y = DISPLAY.height // 2 - 1

# Element 1 is the current time
GROUP.append(adafruit_display_text.label.Label(SMALL_FONT, color=0x808080,
                                               text='12:00', y=-99))
# Element 2 is the current date
GROUP.append(adafruit_display_text.label.Label(SMALL_FONT, color=0x808080,
                                               text='12/31', y=-99))
# Element 3 is the time of (or time to) next event
GROUP.append(adafruit_display_text.label.Label(SMALL_FONT, color=0x00FF00,
                                               text='99d24h24m', y=-99))
# Element 4 is the text for the meeting title

GROUP.append(adafruit_display_text.label.Label(LARGE_FONT, color=0xFF00FF,
                                               text='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA', y=-99))

DISPLAY.show(GROUP)

NETWORK = Network(status_neopixel=board.NEOPIXEL, debug=False)
NETWORK.connect()

# LATITUDE, LONGITUDE, TIMEZONE are set up once, constant over app lifetime

LATITUDE = secrets['latitude']
LONGITUDE = secrets['longitude']
TIMEZONE = secrets['timezone'] # e.g. 'America/New_York'

# get initial clock time, also fetch initial UTC offset while
# here (NOT stored in secrets.py as it may change with DST).
# pylint: disable=bare-except

# lets delay for a few seconds so the internet can fully connect...

try:
    DATETIME, UTC_OFFSET = update_time(TIMEZONE)
except:
    DATETIME, UTC_OFFSET = time.localtime(), '+00:00'
    print("using alternate time\n")
LAST_SYNC = time.mktime(DATETIME)
LAST_EVENT_SYNC = LAST_SYNC



def updateEvent():
    try:
        global nxtEventInt,nxtEventEnd,nxtEventTitle,nxtEventTitleWidth, GROUP, DISPLAY, allDay
                
        # are we connected?

        
        GROUP[3].text="-load-"
        print("Grabbing event\n")
        
        nxtString = NETWORK.fetch_data("http://192.168.1.242:8099/nextEvent.txt")
        # split string into parts
        eventParts = nxtString.split('|')
        # print("Next Event: ", eventParts[0])
        nxtEventInt = int(eventParts[0])
        nxtEventEnd = int(eventParts[1])
        nxtEventTitle = eventParts[2]
        nxtEventTitleWidth = 0

        # if this is an all day event - put a dot somewhere obvious
        if nxtEventTitle.find("all day") > 0:
            print("all day")
            allDay = True
        else :
            allDay = False
        print(nxtEventTitle)
        EVENT_TIME = time.localtime(nxtEventInt) # Convert to struct for later

        for c in nxtEventTitle:
            glyph = LARGE_FONT.get_glyph(ord(c))
            if not glyph:
                continue
            print(glyph.width)
            nxtEventTitleWidth = (nxtEventTitleWidth + glyph.width)

        DISPLAY.refresh()
    except Exception as e:
        print("Error getting event...No idea")
        # try reconnection to wifi - maybe it died?
        NETWORK.connect()
        # try again?
        print(e)

updateEvent()

# MAIN LOOP ----------------------------------------------------------------

while True:
    gc.collect()
    NOW = time.time() # Current epoch time in seconds

    button_down.update()
    button_up.update()
    # check to see if button is pressed?
    if button_up.fell:
        print("buttonUp - Regrabbing event\n")
        updateEvent()
        # print("Updating Time")
        # update_time(TIMEZONE)
    if button_down.fell:
        print("buttonDown\n")
        if (MODE == 0):
            MODE = 1
        else:
            MODE = 0
        print(MODE)
        # reset X for the event title
        titlePosition = 63

    # Need to sync with event data every 15 minutes
    if NOW - LAST_EVENT_SYNC > 15 * 60:
        try:
            print("re-grabbing event\n")
            updateEvent()

            DATETIME, UTC_OFFSET = update_time(TIMEZONE)
            LAST_EVENT_SYNC = time.mktime(DATETIME)
        except:
            LAST_EVENT_SYNC += 15 * 60 # 30 minutes -> seconds

    # Sync with time server every ~12 hours
    if NOW - LAST_SYNC > 12 * 60 * 60:
        try:
            print('is this happening every 12 minutes or every 12 hours?')
            DATETIME, UTC_OFFSET = update_time(TIMEZONE)
            LAST_SYNC = time.mktime(DATETIME)
            continue # Time may have changed; refresh NOW value
        except:
            # update_time() can throw an exception if time server doesn't
            # respond. That's OK, keep running with our current time, and
            # push sync time ahead to retry in 30 minutes (don't overwhelm
            # the server with repeated queries).
            LAST_SYNC += 30 * 60 * 60 # 30 minutes -> seconds

    if DISPLAY.rotation in (0, 180): # Horizontal 'landscape' orientation
        CENTER_X = 48      # Text along right
        MOON_Y = 0         # Moon at left
        TIME_Y = 6         # Time at top right

        # here, we will check to see what mode we're in, and display event title if we're in mode 1
        if MODE == 0:
            EVENT_Y = 26       # Rise/set at bottom right
            TITLE_Y = 16

    frameCounter += 1

    if (frameCounter == SPRITESPEED):
        if (BACKGROUND == 'moon/splash-2.bmp'):
            BACKGROUND = 'moon/splash-1.bmp'
        else:
            BACKGROUND = 'moon/splash-2.bmp'
        frameCounter = 0



    # update to the dark background
    BITMAP = displayio.OnDiskBitmap(open(BACKGROUND, 'rb'))
    TILE_GRID = displayio.TileGrid(BITMAP,
                                   pixel_shader=displayio.ColorConverter(),)
    TILE_GRID.x = 0
    TILE_GRID.y = MOON_Y
    GROUP[LAYER_BACKGROUND] = TILE_GRID

    eventDiff = nxtEventInt - NOW
    eventTime = float(eventDiff)
    day = eventTime // (24 * 3600)

    eventTime = eventTime % (24 * 3600)
    hour = eventTime // 3600
    eventTime %= 3600
    minutes = eventTime // 60
    eventTime %= 60
    seconds = eventTime

    # Update time (GROUP[0]) and date (GROUP[1])

    NOW = time.localtime()
    STRING = hh_mm(NOW)
    GROUP[LAYER_NOWTIME].text = STRING
    GROUP[LAYER_NOWTIME].x = CENTER_X - GROUP[LAYER_NOWTIME].bounding_box[2] // 2
    GROUP[LAYER_NOWTIME].y = TIME_Y

    STRING = str(NOW.tm_mon) + '/' + str(NOW.tm_mday)
    GROUP[LAYER_NOWDATE].text = STRING
    GROUP[LAYER_NOWDATE].x = 0
    GROUP[LAYER_NOWDATE].y = TIME_Y

    # Meeting Time Title

    if eventDiff < 0:
        #eventis currently happening
        STRING = ("-In Mtg-")
        GROUP[LAYER_EVENTDATE].color = (0xFF0000)
    else :
        if day < 1:
            if hour < 1:
                #do something interesting with colors?
                STRING = ("%dm" % (minutes))
                GROUP[LAYER_EVENTDATE].color = (0xFF00FF)
            else:
                STRING = ("%dh%dm" % (hour, minutes))
                GROUP[LAYER_EVENTDATE].color = (0x00FFFF)
        else:
            STRING = ("%dd:%dh%dm" % (day, hour, minutes))
            GROUP[LAYER_EVENTDATE].color = (0xFFFFFF)

    if (len(STRING)>9):
        STRING = "Recurring"

    GROUP[LAYER_EVENTDATE].text = STRING
    XPOS = CENTER_X - (GROUP[LAYER_EVENTDATE].bounding_box[2] + 6) // 2
    GROUP[LAYER_EVENTDATE].x = XPOS
    GROUP[LAYER_EVENTDATE].y = EVENT_Y



    GROUP[LAYER_EVENTTITLE].text = nxtEventTitle[0:40]
    GROUP[LAYER_EVENTTITLE].x = titlePosition
    GROUP[LAYER_EVENTTITLE].y = TITLE_Y

    titlePosition -= 1

    if (titlePosition < (-1*nxtEventTitleWidth - 32)):
        titlePosition = 63


    # if the xpos makes it so the title is off the page, the put it back at the other side?


    # print (GROUP[LAYER_EVENTDATE].bounding_box[2])

    DISPLAY.refresh() # Force full repaint (splash screen sometimes sticks)
    #time.sleep(5)