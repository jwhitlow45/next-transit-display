# Next Transit Display

Display estimated arrival information about your local transit stops on an LED matrix display using the OpenData511 API

## BOM (~$100)
- [Adafruit LED Matrix](https://www.adafruit.com/category/327) - 64x32 is a good size for displaying 4 transit lines with next 2 arrival times each
- [Adafruit RGB Matrix Bonnet](https://www.adafruit.com/product/3211)
- [5V 4A switching power supply](https://www.adafruit.com/product/1466)
- Raspberry Pi >=3 - slower Pis may experience display flickering issues, feel free to test it out but if you're buying new get at least a Pi 4

## Requirements
- OS: Linux (headless Raspberry Pi OS using Bookworm 64-bit recommended)
- Python 3.11.2 (newest version of Python I could build `rpi-rgb-led-matrix` with)
- git

The prebuilt binary below needs only the OS. Python and git are for the install script and for development.

## Setup
### Prebuilt binary
Each [GitHub release](https://github.com/jwhitlow45/next-transit-display/releases) has a standalone build for 64-bit Raspberry Pi OS Bookworm, with Python, every dependency and the LED matrix library bundled. It needs no install script. [BUILDING.md](BUILDING.md) covers installing it as a service, and building and releasing it yourself.

### Install script (requires root)
```
sudo su
chmod +x ./setup.sh
./setup.sh
```
This will:
- Build and install [`rpi-rgb-led-matrix`](https://github.com/hzeller/rpi-rgb-led-matrix) to global Python
- Install the uv package manager to root user
- Install `next-transit-display` dependencies to global Python
- Copies the `.env.example` to `.env` for you to configure

Unfortunately due to the low-level nature of this project I am unaware of a way to get around installing the Python packages globally. `rpi-rgb-led-matrix` also requires being run as root to function properly leading to all of this project's dependencies needing to be installed to root.

Total installation time is ~2 minutes on a Raspberry Pi 3.

While the above setup script copies the `.env.example` to `.env` it still requires configuration. Each environment variable is documented in [ENVIRONMENT.md](ENVIRONMENT.md). Be sure to follow the instructions carefully.

### Running the program (requires root)
Run the `main.py` file in the root of the project:
```
sudo python3 main.py
```
It can also be run as a background process with `nohup` so it persists after your terminal is closed:
```
sudo nohup python3 main.py &
```

## Development
This project relies on two separate environments to be developed. One on your local machine and one on the Raspberry Pi.

Development can be done on the Raspberry Pi directly, but unless you have a more powerful one that can better handle remote-IDE setups, I highly recommend using your favorite remote file‑syncing tool to deploy your changes to your Pi otherwise you will wait 5 minutes for every linter update.

### Raspberry Pi Environment Setup
Run the setup script as shown above.

If doing development directly on the Pi also configure environment variables which are in [ENVIRONMENT.md](ENVIRONMENT.md).

### Local Machine Environment Setup
#### Setup Python virtual environment and install dependencies
```
uv sync
```

#### Configure Environment Variables
Configure environment variables which are in [ENVIRONMENT.md](ENVIRONMENT.md).

#### Deploying changes
I found it simple enough to use rsync and scp to send files from my local machine to my Pi after making changes. The following command executed from the root of the repo accomplishes that:
```
rsync -aPh --delete --filter=':- .gitignore' --exclude=.git/ . <user>@<host>:<path-to-remote-project> && scp .env <user>@<host>:<path-to-remote-project>/.env
```
As always use whatever workflow works for you.

#### Executing changes
To execute changes I recommend using the `-B` flag to avoid creating `__pycache__` files. They cause permission conflicts with the above rsync + scp method od "deployment":
```
sudo python3 -B main.py
```

There is also support for a `LOG_LEVEL` environment variable supporting the usual `fatal|error|warning|info|debug` log levels. I'll be honest I kinda chucked in debug statements wherever I thought they would be helpful without thinking about traceability. I've never been a super low-level engineer so I have little to no experience writing professional debug logs. The option is there though.

#### Testing
This project didn't feel significant enough to warrant a test suite implementation. I'm not a Python developer and this already took me quite a while to design to be as robust as it is. Feel free to write tests for the code and PR them. I'm not going to.

