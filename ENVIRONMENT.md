Link back to [README.md](README.md).

(I hate when projects don't do this)

---

## Environment Variables
Variables set to non-empty strings ("\<value\>") or that are pre-populated are required

Variables set to empty strings ("") are optional

### OpenData511 variables
#### OPEN_DATA_511_API_KEY_0/OPEN_DATA_511_API_KEY_1
```
OPEN_DATA_511_API_KEY_0="<api-key>"
OPEN_DATA_511_API_KEY_1=""
```
Get an API key here - https://511.org/open-data/token

OpenData511 is not responding to requests for rate limit increases, meaning if you want to monitor more than one stop per minute you must use an additional API key. Please use this responsibly and do not abuse their API.

Only `OPEN_DATA_511_API_KEY_0` is required, but `OPEN_DATA_511_API_KEY_1` can be provided to "double" the program's rate limit from 60 to 120 requests per hour.

#### OPEN_DATA_511_AGENCY_ID
```
OPEN_DATA_511_AGENCY_ID="<agency-id>"
```
Agency ID of the transit agency you wish to monitor the stops of

Your transit agency's agency ID can be found by visiting the following url: `https://api.511.org/transit/operators?api_key=<your-api-key>`

#### OPEN_DATA_511_STOPCODES
```
OPEN_DATA_511_STOPCODES="<stopcode-0>,<stopcode-1>"
```
Comma-delimited list of stopcodes to monitor. These are the unique ids assigned to transit stops by a transit agency and should be accessible via your transit agencies website. Alternatively, visit the following URL and search for `StopPointRef` in the returned XML document: `https://api.511.org/transit/StopMonitoring?api_key=<your-api-key>&agency=<your-agency-id>`

### LED Matrix variables
These are all values inherent to `rpi-rgb-led-matrix`. See the linked documentation for how they should be configured.

[Panel configuration](https://github.com/hzeller/rpi-rgb-led-matrix?tab=readme-ov-file#types-of-displays)
```
LED_MATRIX_ROWS="<integer>"
LED_MATRIX_COLS="<integer>"
LED_MATRIX_CHAIN_LENGTH="<integer>"
LED_MATRIX_PARALLEL="<integer>"
```

[GPIO speed](https://github.com/hzeller/rpi-rgb-led-matrix?tab=readme-ov-file#gpio-speed)
```
LED_MATRIX_GPIO_SLOWDOWN="10"
```
Recommended to use the highest slowdown value of 10 to give lowest chance of display flickering

[Hardware mappings](https://github.com/hzeller/rpi-rgb-led-matrix/blob/master/wiring.md#alternative-hardware-mappings)
```
LED_MATRIX_HARDWARE_MAPPING="<hardware-mapping>"
```
This will be `adafruit-hat` if you use the Adafruit RGB Matrix Bonnet linked in the BOM

[Brightness](https://github.com/hzeller/rpi-rgb-led-matrix?tab=readme-ov-file#misc-options)
```
LED_MATRIX_MAX_BRIGHTNESS="<integer>"
```

### Refresh interval variables
#### REFRESH_API_INTERVAL_SECONDS
```
REFRESH_API_INTERVAL_SECONDS="62"
```
How often new data is fetched from the OpenData511 API. Recommended default of 62 to be just above default rate limit of 60 requests per hour.

All stopcodes are checked every `REFRESH_API_INTERVAL_SECONDS`, each requiring their own request, so the minimum `REFRESH_API_INTERVAL_SECONDS` can be calculated to be:
```
(number of comma-delimited OPEN_DATA_511_STOPCODES * 60) / number of API keys provided
```

It is recommended to set `REFRESH_API_INTERVAL_SECONDS` slightly higher than the calculated value to avoid running into the rate-limit.

#### REFRESH_DISPLAY_INTERVAL_SECONDS
```
REFRESH_DISPLAY_INTERVAL_SECONDS="5"
```
How often arrival time calculations are performed based on data fetched from the API and written to the display. Recommended default of 5.

It is necessary for this to be separate from `REFRESH_API_INTERVAL_SECONDS` to allow minutes until arrival time to be re-calculated and updated independent of API requests.


### Line disambiguation symbols (optional)
```
LINE_REFERENCES=""
LINE_STOPCODES=""
LINE_DISAMBIGUATION_SYMBOLS=""
```
When multiple transit lines share the same reference but travel in different directions (or serve different stops), you can use these variables to assign unique symbols next to line references on your display.

#### LINE_REFERENCES
Comma-separated list of line references that need disambiguation.

There should be an entry for each line + stopcode combination needing disambiguation.

Example: Line 1 and line 2 both serve stops A and B, but in different directions:
```
LINE_REFERENCES="1,2,1,2"
```

#### LINE_STOPCODES
Comma-separated list of stopcodes corresponding to each entry in LINE_REFERENCES.

Each entry matches up to a corresponding entry at the same position in LINE_REFERENCES.

Example: The first two entries in `LINE_REFERENCES` are for stop A and the next two for stop B:
```
LINE_STOPCODES="A,A,B,B"
```

#### LINE_DISAMBIGUATION_SYMBOLS
Comma-separated list of symbols (like N, S, E, W) to display for each line/stop combination.

Each symbol matches the same position as in the other two variables.

Example: Line 1 at stop A is northbound, line 2 at stop A is westbound, line 1 at stop B is southbound, and line 2 at stop B is eastbound:
```
LINE_DISAMBIGUATION_SYMBOLS="N,W,S,E"
```
NOTE: these can be whatever you want, including arrows or even multiple characters, just ensure there is room on your display

**Putting It All Together:**

Each position in the three lists corresponds to a unique (line, stop) pair and its symbol:

| LINE_REFERENCES | LINE_STOPCODES | LINE_DISAMBIGUATION_SYMBOLS |
|:---:|:---:|:---:|
| 1 | A | N |
| 2 | A | W |
| 1 | B | S |
| 2 | B | E |

Make sure all three variables have the same number of entries, and that the entries correspond to the correct reference, stopcode, and symbol across all lists.

Previous example configuration:
```
LINE_REFERENCES="1,2,1,2"
LINE_STOPCODES="A,A,B,B"
LINE_DISAMBIGUATION_SYMBOLS="N,W,S,E"
```
Example output:
```
1N 10 20
2W 10 20
1S 10 20
2E 10 20
```

If only some lines require disambiguation those which don't can be omitted but spacing may be affected.

Example configuration where stopcode B services line 2 and 3:
```
LINE_REFERENCES="1,1"
LINE_STOPCODES="A,B"
LINE_DISAMBIGUATION_SYMBOLS="N,S"
```
Example output:
```
1N 10 20
2 10 20
1S 10 20
3 10 20
```

Spaces (" ") can be used as a blank to keep stops which don't have disambiguation in alignment with those that do.

Example configuration where stopcode B services line 2 and 3 with spacing:
```
LINE_REFERENCES="1,2,1,3"
LINE_STOPCODES="A,A,B,B"
LINE_DISAMBIGUATION_SYMBOLS="N, ,S, "
```
Example output:
```
1N 10 20
2  10 20
1S 10 20
3  10 20
```

### Display info configuration
#### LINE_REFERENCE_ORDER
```
LINE_REFERENCE_ORDER="LINE_REFERENCE"
```
Parameter which should be used to determine in which order line references should be displayed, the following parameter options are valid:
```
LINE_REFERENCE ARRIVAL_TIME
```
#### FUTURE_STOP_VISITS_SHOWN
```
FUTURE_STOP_VISITS_SHOWN="2"
```
How many future stop visits should be shown per line on the display

### Font configuration
#### FONT
```
FONT="5x7.bdf"
```
Font of the display, see `fonts/` directory

#### FONT_COLOR
```
COLOR="<color-string>"
```
Color of font on the display, the following color options are valid:
```
BLACK WHITE RED GREEN BLUE YELLOW CYAN MAGENTA GRAY ORANGE PURPLE BROWN PINK LIME NAVY TEAL OLIVE MAROON SILVER GOLD MUNI MUNI_LESS MUNI_ALT MUNI_ALT_LESS
```
NOTE: These are just default RGB color values I ripped from the internet. Some of them are pretty off on LED matrix displays. Feel free to modify any of them by going into `modules/display_utils.py` and tweaking the RGB values by hand, or adding your own color entries.

#### FONT_X_ALIGNMENT
```
FONT_X_ALIGNMENT="CENTER"
```
Alignment of text in the X (left/right) direction, the following alignment options are valid:
```
CENTER LEFT
```

### Development
#### LOG_LEVEL
```
LOG_LEVEL=<fatal|error|warning|info|debug>
```
Sets the log level of the program. If you're using this I assume you know what you're doing so not going to get into it.

---

Link back to [README.md](README.md).

(Seriously, just give me a document tree to crawl dammit)