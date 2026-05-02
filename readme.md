# BeatSchool - Movement Analysis Game

BeatSchool is an interactive movement analysis game designed for groups of up to 10 friends. Players synchronize their physical movements (pitch and roll) to the rhythm of a song, with real-time feedback and scoring based on their timing and coordination.

## Architecture

The system consists of two main components:

### Firmware (tt-firmware/)
- **Hardware**: ESP8266-based microcontrollers (D1 Mini) equipped with MPU6050 IMU sensors and WS2812B LED strips
- **Communication**: ESP-NOW wireless protocol for low-latency data streaming
- **Features**:
  - Real-time pitch/roll data acquisition from IMU
  - LED feedback for game states and scoring
  - Wireless mesh networking for multi-device coordination

### Coordinator (Python Backend)
- **Framework**: Flask web application serving the game interface
- **Audio Analysis**: Librosa-based beat detection and onset analysis for songs
- **Real-time Processing**: Serial communication with ESP-NOW bridge device
- **Game Logic**: Movement analysis, scoring, and session management

## Features

- **Real-time Movement Tracking**: 10-player simultaneous IMU data streaming
- **Audio Synchronization**: Automatic beat detection and rhythm analysis
- **Visual Feedback**: LED indicators on each device for game state
- **Web Interface**: Live game dashboard with scoring and analytics
- **Session Management**: Complete game sessions with final scoring

## Hardware Build

Each node (player) is:

- ESP8266 D1 Mini board
- MPU6050 IMU sensor
- WS2812B LED strips (32 LEDs each)

One coordinator reciever ESP8266 board connected over wifi is needed as well.

## Installation

### Firmware Setup

1. Install PlatformIO:
   ```bash
   pip install platformio
   ```

2. Build and upload to devices:
   ```bash
   cd tt-firmware
   pio run -e d1mini -t upload
   ```

### Coordinator Setup

1. Install Python dependencies:
   ```bash
   cd coordinator
   pip install -r requirements.txt
   ```

## Running the Game

1. Add songs to a `songs/` folder inside the project folder.

1. **Start the Coordinator**:
   ```bash
   python main.py --help
   ```
   Shows you the command-line options. Things like serial connection, etc.

2. **Open the Web Interface**:
   Open `http://localhost:5000` in your browser

3. **Game Flow**:
   - Players devices are connected and streaming data
   - Game-runner chooses a song from the dropdown (optional)
   - Game-runner presses play
   - Game starts with audio playback
   - Real-time movement analysis and scoring
   - Final scores displayed at session end

