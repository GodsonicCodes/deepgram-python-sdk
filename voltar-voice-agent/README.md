# Voltar AI Voice Sales Agent - Backend APIs

Production-ready backend APIs for a conversational voice sales agent that speaks like Alex Hormozi. Built on top of the Deepgram Python SDK.

## Features

- **Real-time Voice Pipeline**: User speaks → Deepgram STT → Claude AI → Deepgram TTS → Audio response
- **Low Latency**: < 800ms response time with streaming architecture
- **Voice Activity Detection**: Detects when user interrupts agent (< 300ms response)
- **Lead Extraction**: Automatically captures contact info and pain points during conversation
- **Alex Hormozi Persona**: Direct, value-focused sales approach
- **WebSocket + REST APIs**: Complete API suite for frontend integration
- **Production Ready**: Deploys to Render with health checks

## Architecture

```
┌─────────────┐
│   Browser   │
│  (Frontend) │
└──────┬──────┘
       │ WebSocket
       ▼
┌─────────────────────────────────┐
│      FastAPI Backend            │
│  ┌──────────────────────────┐   │
│  │   Voice Pipeline         │   │
│  │                          │   │
│  │  User Audio              │   │
│  │      ↓                   │   │
│  │  Deepgram STT (streaming)│   │
│  │      ↓                   │   │
│  │  Claude Sonnet 4         │   │
│  │   (streaming)            │   │
│  │      ↓                   │   │
│  │  Deepgram TTS (streaming)│   │
│  │      ↓                   │   │
│  │  Audio Response          │   │
│  └──────────────────────────┘   │
│                                  │
│  Session Manager | Lead Tracker │
└──────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.9+
- Deepgram API key ([get one here](https://console.deepgram.com/signup))
- Anthropic API key ([get one here](https://console.anthropic.com/))

### Installation

1. **Clone and navigate to the project**:
```bash
cd voltar-voice-agent
```

2. **Create virtual environment**:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**:
```bash
pip install -r requirements.txt
```

4. **Set up environment variables**:
```bash
cp .env.example .env
# Edit .env and add your API keys
```

5. **Run the server**:
```bash
python main.py
```

Server will start on `http://localhost:10000`

## API Documentation

### WebSocket API

#### `/ws/voice-session`
Main WebSocket endpoint for voice sessions (handles text control messages).

#### `/ws/voice-session-binary`
WebSocket endpoint that handles both binary audio and text control messages.

**Client → Server Messages:**

```python
# Start session
{
  "type": "start_session",
  "userId": "optional-user-id"
}

# Send audio chunk (binary WebSocket only)
# Send raw audio bytes (linear16, 16kHz, mono)

# User interrupted agent
{
  "type": "interrupt"
}

# End session
{
  "type": "end_session"
}
```

**Server → Client Messages:**

```python
# Session started
{
  "type": "session_started",
  "sessionId": "uuid",
  "websocketUrl": "ws://..."
}

# Agent starts speaking
{
  "type": "agent_speaking_start"
}

# Audio chunk from agent
{
  "type": "agent_audio_chunk",
  "data": [byte_array],  # linear16, 24kHz
  "sequence": 1
}

# Agent finished speaking
{
  "type": "agent_speaking_end"
}

# Transcript update
{
  "type": "transcript_update",
  "message": {
    "role": "user" | "agent",
    "text": "transcript text",
    "timestamp": 1234567890,
    "isFinal": true
  }
}

# Audio levels for waveform
{
  "type": "audio_levels",
  "source": "user" | "agent",
  "level": 75  # 0-100
}

# State change
{
  "type": "state_change",
  "state": "waiting" | "listening" | "speaking"
}

# Error
{
  "type": "error",
  "message": "error description"
}
```

### REST API Endpoints

#### `POST /api/sessions/start`
Start a new voice session.

**Response:**
```json
{
  "sessionId": "uuid",
  "websocketUrl": "ws://localhost:10000/ws/voice-session"
}
```

#### `GET /api/sessions/{sessionId}`
Get session information.

**Response:**
```json
{
  "sessionId": "uuid",
  "status": "active",
  "duration": 120,
  "messageCount": 8
}
```

#### `POST /api/sessions/{sessionId}/end`
End a session.

**Response:**
```json
{
  "summary": {
    "duration": 120,
    "messageCount": 8,
    "leadCaptured": true
  }
}
```

#### `GET /api/sessions/{sessionId}/transcript`
Get full conversation transcript.

**Response:**
```json
{
  "messages": [
    {
      "role": "agent",
      "text": "Hey! Thanks for checking out Voltar AI...",
      "timestamp": 1234567890
    },
    {
      "role": "user",
      "text": "I'm interested in automation",
      "timestamp": 1234567895
    }
  ]
}
```

#### `POST /api/leads`
Create a lead from session data.

**Request:**
```json
{
  "sessionId": "uuid",
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "555-1234",
  "painPoints": ["manual processes", "high costs"],
  "interestLevel": "high"
}
```

**Response:**
```json
{
  "leadId": "uuid",
  "qualificationScore": 85
}
```

#### `GET /api/health`
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "services": {
    "deepgram": "up",
    "claude": "up"
  }
}
```

## Alex Hormozi Sales Persona

The agent uses a system prompt designed to emulate Alex Hormozi's direct, value-focused sales style:

- **Direct communication**: No fluff, straight to value
- **Outcome-focused**: Emphasizes results, not features
- **Qualifying questions**: Budget, timeline, authority (BANT)
- **Short responses**: 2-3 sentences max for natural conversation
- **Clear next steps**: Always moving toward demo/trial/call

### Example Conversation Flow

1. **Greeting + Open Question**
   - "Hey! Thanks for checking out Voltar AI. What brought you here today?"

2. **Discover Challenge**
   - User: "We're struggling with customer support"
   - Agent: "What's that costing you right now? Both in dollars and time."

3. **Show Value**
   - "So if you could cut support costs by 70% and respond in under a minute, what would that be worth?"

4. **Handle Objections**
   - User: "That sounds expensive"
   - Agent: "Compared to what? Right now you're paying X per month in support staff. This is a fraction of that."

5. **Close**
   - "Want to see it in action? I can get you into a demo this week."

## Deployment to Render

### Option 1: Deploy via Dashboard

1. Push code to GitHub
2. Create new Web Service on [Render](https://render.com)
3. Connect your repository
4. Use these settings:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Environment**: Python 3
5. Add environment variables:
   - `DEEPGRAM_API_KEY`
   - `ANTHROPIC_API_KEY`

### Option 2: Deploy via Blueprint (render.yaml)

1. Push code to GitHub (including `render.yaml`)
2. In Render dashboard: "New" → "Blueprint"
3. Select your repository
4. Render will auto-detect `render.yaml` and configure everything
5. Add your API keys in the environment variables section

### Environment Variables on Render

Required:
- `DEEPGRAM_API_KEY`: Your Deepgram API key
- `ANTHROPIC_API_KEY`: Your Anthropic API key

Optional:
- `PORT`: Defaults to 10000 (Render sets this automatically)
- `DEEPGRAM_MODEL`: Defaults to `nova-2`
- `CLAUDE_MODEL`: Defaults to `claude-sonnet-4-20250514`

## Frontend Integration

### Example: Connecting to WebSocket

```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:10000/ws/voice-session-binary');

// Start session
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: 'start_session',
    userId: 'user-123'
  }));
};

// Handle messages
ws.onmessage = (event) => {
  if (typeof event.data === 'string') {
    const msg = JSON.parse(event.data);

    if (msg.type === 'agent_audio_chunk') {
      // Play audio
      playAudioChunk(new Uint8Array(msg.data));
    }

    if (msg.type === 'transcript_update') {
      // Update UI with transcript
      updateTranscript(msg.message);
    }

    if (msg.type === 'state_change') {
      // Update UI state
      updateState(msg.state);
    }
  }
};

// Send audio from microphone
navigator.mediaDevices.getUserMedia({ audio: true })
  .then(stream => {
    const audioContext = new AudioContext({ sampleRate: 16000 });
    const source = audioContext.createMediaStreamSource(stream);
    const processor = audioContext.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (e) => {
      const audioData = e.inputBuffer.getChannelData(0);
      // Convert to 16-bit PCM
      const pcm = convertToPCM16(audioData);
      // Send to server
      ws.send(pcm);
    };

    source.connect(processor);
    processor.connect(audioContext.destination);
  });

// Interrupt agent
function interruptAgent() {
  ws.send(JSON.stringify({ type: 'interrupt' }));
}

// End session
function endSession() {
  ws.send(JSON.stringify({ type: 'end_session' }));
}
```

## Performance Optimization

### Latency Targets

- **Response Latency**: < 800ms (STT → Claude → TTS → Audio)
- **WebSocket Latency**: < 100ms
- **Interruption Response**: < 300ms

### Optimization Tips

1. **Use Streaming**: All components (STT, Claude, TTS) stream data
2. **Start TTS Early**: Begin TTS as soon as Claude returns first tokens
3. **VAD Tuning**: Adjust `endpointing` and `utterance_end_ms` in STT config
4. **Audio Buffering**: Keep buffers small to minimize latency
5. **Connection Pooling**: Reuse WebSocket connections when possible

## Project Structure

```
voltar-voice-agent/
├── main.py                 # FastAPI app with WebSocket & REST endpoints
├── voice_pipeline.py       # Core pipeline (STT → Claude → TTS)
├── session_manager.py      # Session state tracking
├── lead_extractor.py       # Lead extraction and qualification
├── requirements.txt        # Python dependencies
├── render.yaml            # Render deployment config
├── .env.example           # Environment variable template
└── README.md              # This file
```

## Development

### Running in Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
uvicorn main:app --reload --port 10000
```

### Testing WebSocket Connection

Use a WebSocket client like [websocat](https://github.com/vi/websocat):

```bash
websocat ws://localhost:10000/ws/voice-session
```

Then send test messages:
```json
{"type": "start_session", "userId": "test-user"}
```

## Troubleshooting

### Common Issues

**1. "Connection refused" on WebSocket**
- Ensure server is running: `python main.py`
- Check firewall settings
- Verify correct port (default: 10000)

**2. "API key invalid" errors**
- Verify `.env` file exists and has correct keys
- Check API key format (no quotes, no spaces)
- Confirm keys are active in respective dashboards

**3. High latency / slow responses**
- Check internet connection
- Verify Deepgram model (`nova-2` is fastest)
- Consider using `haiku` model for Claude (faster, but less capable)
- Check server logs for bottlenecks

**4. Audio not playing**
- Verify audio format matches (linear16 PCM)
- Check sample rates: STT=16kHz, TTS=24kHz
- Test with simple audio playback first

**5. VAD not detecting interruptions**
- Adjust `endpointing` parameter (default: 300ms)
- Check `vad_events` is enabled in STT config
- Verify audio levels are sufficient

## Performance Benchmarks

Typical performance on Render Starter instance:

- **Cold start**: 2-3 seconds
- **Response time**: 600-900ms
- **Concurrent sessions**: 20-30
- **Memory usage**: 200-300 MB per session

## Security Notes

**Production Checklist:**

- [ ] Use HTTPS/WSS instead of HTTP/WS
- [ ] Configure CORS properly (don't use `*` in production)
- [ ] Add authentication/authorization
- [ ] Rate limit API endpoints
- [ ] Validate and sanitize all inputs
- [ ] Store API keys securely (use Render secrets)
- [ ] Enable logging and monitoring
- [ ] Set up error alerting

## License

Built on top of the Deepgram Python SDK. See Deepgram's license for SDK terms.

## Support

For issues related to:
- **Deepgram SDK**: [Deepgram Support](https://developers.deepgram.com/)
- **Anthropic API**: [Anthropic Documentation](https://docs.anthropic.com/)
- **This project**: Open an issue in the repository

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

**Built with ❤️ for Voltar AI**
