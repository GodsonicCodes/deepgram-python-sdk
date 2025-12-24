"""
Voice Pipeline - Deepgram STT → Claude → Deepgram TTS
Handles streaming audio processing with low latency
"""

import asyncio
import json
import time
import os
from typing import Optional, List
from collections import deque

from deepgram import DeepgramClient, AsyncDeepgramClient
from deepgram.core.events import EventType
from anthropic import AsyncAnthropic

from session_manager import SessionManager
from lead_extractor import LeadExtractor

# Alex Hormozi sales persona system prompt
SYSTEM_PROMPT = """
You are a sales assistant for Voltar AI, speaking like Alex Hormozi.

Style:
- Direct, no fluff
- Focus on VALUE and OUTCOMES, not features
- Ask qualifying questions: budget, timeline, authority
- Use specific numbers when possible
- Keep responses SHORT (2-3 sentences max)
- Natural speech, use contractions
- Sound conversational and energetic

Flow:
1. Greeting + value statement + open question
2. Discover their challenge/problem
3. Show how Voltar AI solves it (outcomes focused)
4. Handle objections with logic
5. Close with clear next step (demo/trial/call)

Example opening:
"Hey! Thanks for checking out Voltar AI. What's the biggest challenge you're facing with AI automation?"

Qualification questions:
- "What have you tried so far?"
- "How much is this costing you per month?"
- "If you could solve this, what would that be worth?"

Always move toward: booking demo, starting trial, or scheduling call.

IMPORTANT: Keep responses conversational and SHORT. No more than 2-3 sentences per response.
"""

GREETING_MESSAGE = "Hey! Thanks for checking out Voltar AI. What brought you here today?"


class VoicePipeline:
    """
    Manages the complete voice pipeline:
    User Audio → Deepgram STT → Claude → Deepgram TTS → User
    """

    def __init__(
        self,
        session_id: str,
        websocket,
        session_manager: SessionManager,
        lead_extractor: LeadExtractor,
        deepgram_api_key: str,
        anthropic_api_key: str,
        deepgram_model: str = "nova-2",
        claude_model: str = "claude-sonnet-4-20250514"
    ):
        self.session_id = session_id
        self.websocket = websocket
        self.session_manager = session_manager
        self.lead_extractor = lead_extractor

        # API clients
        self.deepgram_client = AsyncDeepgramClient(api_key=deepgram_api_key)
        self.anthropic_client = AsyncAnthropic(api_key=anthropic_api_key)

        # Models
        self.deepgram_model = deepgram_model
        self.claude_model = claude_model

        # Deepgram connections
        self.stt_connection = None
        self.tts_connection = None

        # State
        self.is_running = False
        self.is_speaking = False
        self.current_state = "waiting"
        self.conversation_history: List[dict] = []

        # Audio buffers
        self.audio_buffer = deque(maxlen=100)
        self.tts_audio_sequence = 0

        # VAD state
        self.last_audio_time = 0
        self.silence_threshold = 0.3  # 300ms for interruption
        self.speech_detected = False

        # Tasks
        self.tasks = []

    async def start(self):
        """Start the voice pipeline"""
        self.is_running = True

        # Update session state
        await self._update_state("waiting")

        # Initialize Deepgram STT connection
        await self._init_stt_connection()

        # Send agent's first message (greeting)
        await self._agent_speak(GREETING_MESSAGE)

    async def stop(self):
        """Stop the voice pipeline"""
        self.is_running = False
        await self.cleanup()

    async def cleanup(self):
        """Clean up connections and resources"""
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Close Deepgram connections using websocket close
        if self.stt_connection:
            try:
                await self.stt_connection._websocket.close()
            except:
                pass

        if self.tts_connection:
            try:
                await self.tts_connection._websocket.close()
            except:
                pass

    async def process_audio_chunk(self, audio_data: bytes):
        """Process incoming audio chunk from user"""
        if not self.is_running or not self.stt_connection:
            return

        # Send to Deepgram STT
        await self.stt_connection.send(audio_data)

        # Calculate audio level for waveform visualization
        level = self._calculate_audio_level(audio_data)
        await self._send_audio_level("user", level)

        # Update last audio time for VAD
        if level > 10:  # Threshold for speech detection
            self.last_audio_time = time.time()
            if not self.speech_detected:
                self.speech_detected = True
                await self._update_state("listening")

    async def handle_interrupt(self):
        """Handle user interruption of agent speaking"""
        if self.is_speaking:
            print(f"[{self.session_id}] User interrupted agent")
            self.is_speaking = False

            # Stop TTS immediately
            if self.tts_connection:
                try:
                    # Send flush to clear any pending audio
                    from deepgram.extensions.types.sockets import SpeakV1ControlMessage
                    await self.tts_connection.send_control(
                        SpeakV1ControlMessage(type="Flush")
                    )
                except:
                    pass

            await self._update_state("listening")

    async def _init_stt_connection(self):
        """Initialize Deepgram STT WebSocket connection"""
        try:
            # Connect to Deepgram STT with streaming (v2 API for better conversational support)
            # Note: v2 API uses string parameters
            options = {
                "model": self.deepgram_model,
                "encoding": "linear16",
                "sample_rate": "16000",  # v2 API uses strings
                "eot_threshold": "300",  # 300ms silence for end of turn
                "eot_timeout_ms": "1000"  # Max 1s between words
            }

            # Create connection using async context manager
            self.stt_connection = await self.deepgram_client.listen.v2.connect(**options).__aenter__()

            # Set up event handlers
            self.stt_connection.on(EventType.OPEN, self._on_stt_open)
            self.stt_connection.on(EventType.MESSAGE, self._on_stt_message)
            self.stt_connection.on(EventType.ERROR, self._on_stt_error)
            self.stt_connection.on(EventType.CLOSE, self._on_stt_close)

            # Start listening
            task = asyncio.create_task(self.stt_connection.start_listening())
            self.tasks.append(task)

        except Exception as e:
            print(f"Error initializing STT: {e}")
            await self._send_error(f"Failed to initialize speech recognition: {str(e)}")

    async def _on_stt_open(self, *args):
        """STT connection opened"""
        print(f"[{self.session_id}] STT connection opened")

    async def _on_stt_message(self, message):
        """Handle STT transcription results"""
        try:
            msg_type = getattr(message, "type", "Unknown")

            if msg_type == "Results":
                # Get transcript
                channel = message.channel
                if not channel or not channel.alternatives:
                    return

                alternative = channel.alternatives[0]
                transcript = alternative.transcript
                is_final = message.is_final

                if not transcript or transcript.strip() == "":
                    return

                # Send transcript update to frontend
                await self._send_transcript_update(
                    role="user",
                    text=transcript,
                    is_final=is_final
                )

                # If final, process with Claude
                if is_final:
                    print(f"[{self.session_id}] User said: {transcript}")
                    await self._process_user_input(transcript)

            elif msg_type == "SpeechStarted":
                # User started speaking
                print(f"[{self.session_id}] Speech started")
                self.speech_detected = True

                # If agent is speaking, interrupt
                if self.is_speaking:
                    await self.handle_interrupt()

            elif msg_type == "UtteranceEnd":
                # User stopped speaking
                print(f"[{self.session_id}] Utterance ended")
                self.speech_detected = False

        except Exception as e:
            print(f"Error processing STT message: {e}")

    async def _on_stt_error(self, error):
        """STT error handler"""
        print(f"[{self.session_id}] STT error: {error}")

    async def _on_stt_close(self, *args):
        """STT connection closed"""
        print(f"[{self.session_id}] STT connection closed")

    async def _process_user_input(self, user_text: str):
        """Process user input with Claude"""
        try:
            # Add to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": user_text
            })

            # Add to session
            session = self.session_manager.get_session(self.session_id)
            if session:
                session.add_message("user", user_text)

            # Extract lead information in background
            asyncio.create_task(
                self.lead_extractor.extract_from_text(
                    self.session_id,
                    user_text,
                    self.conversation_history
                )
            )

            # Get Claude response (streaming)
            response_text = await self._get_claude_response()

            if response_text:
                # Speak the response
                await self._agent_speak(response_text)

        except Exception as e:
            print(f"Error processing user input: {e}")
            await self._send_error(f"Error processing your message: {str(e)}")

    async def _get_claude_response(self) -> str:
        """Get streaming response from Claude"""
        try:
            # Prepare messages
            messages = self.conversation_history.copy()

            # Call Claude with streaming
            response_text = ""

            async with self.anthropic_client.messages.stream(
                model=self.claude_model,
                max_tokens=200,  # Keep responses short
                system=SYSTEM_PROMPT,
                messages=messages
            ) as stream:
                async for text in stream.text_stream:
                    response_text += text

            # Add to conversation history
            self.conversation_history.append({
                "role": "assistant",
                "content": response_text
            })

            # Add to session
            session = self.session_manager.get_session(self.session_id)
            if session:
                session.add_message("agent", response_text)

            print(f"[{self.session_id}] Agent response: {response_text}")

            return response_text

        except Exception as e:
            print(f"Error getting Claude response: {e}")
            return "I apologize, I'm having trouble processing that. Could you repeat?"

    async def _agent_speak(self, text: str):
        """Convert text to speech and stream to user"""
        try:
            # Send transcript update
            await self._send_transcript_update(
                role="agent",
                text=text,
                is_final=True
            )

            # Update state
            self.is_speaking = True
            await self._update_state("speaking")
            await self._send_message({"type": "agent_speaking_start"})

            # Initialize TTS connection if needed
            if not self.tts_connection:
                await self._init_tts_connection()

            # Send text to TTS
            if self.tts_connection:
                from deepgram.extensions.types.sockets import SpeakV1TextMessage
                # SpeakV1TextMessage requires type="Speak" and text field
                text_message = SpeakV1TextMessage(type="Speak", text=text)
                await self.tts_connection.send_text(text_message)

                # Wait for TTS to complete
                await asyncio.sleep(0.1)  # Small delay to ensure audio starts

                # Send flush to complete
                from deepgram.extensions.types.sockets import SpeakV1ControlMessage
                await self.tts_connection.send_control(
                    SpeakV1ControlMessage(type="Flush")
                )

        except Exception as e:
            print(f"Error in agent speak: {e}")
            self.is_speaking = False
            await self._update_state("listening")

    async def _init_tts_connection(self):
        """Initialize Deepgram TTS WebSocket connection"""
        try:
            options = {
                "model": "aura-asteria-en",
                "encoding": "linear16",
                "sample_rate": "24000"  # v1 API uses strings
            }

            # Create connection using async context manager
            self.tts_connection = await self.deepgram_client.speak.v1.connect(**options).__aenter__()

            # Set up event handlers
            self.tts_connection.on(EventType.OPEN, self._on_tts_open)
            self.tts_connection.on(EventType.MESSAGE, self._on_tts_message)
            self.tts_connection.on(EventType.ERROR, self._on_tts_error)
            self.tts_connection.on(EventType.CLOSE, self._on_tts_close)

            # Start listening
            task = asyncio.create_task(self.tts_connection.start_listening())
            self.tasks.append(task)

        except Exception as e:
            print(f"Error initializing TTS: {e}")

    async def _on_tts_open(self, *args):
        """TTS connection opened"""
        print(f"[{self.session_id}] TTS connection opened")

    async def _on_tts_message(self, message):
        """Handle TTS audio chunks"""
        try:
            if isinstance(message, bytes):
                # Audio data
                if self.is_speaking:
                    # Send to client
                    await self._send_audio_chunk(message)

                    # Calculate audio level
                    level = self._calculate_audio_level(message)
                    await self._send_audio_level("agent", level)

            else:
                msg_type = getattr(message, "type", "Unknown")

                if msg_type == "Flushed":
                    # TTS completed
                    self.is_speaking = False
                    await self._send_message({"type": "agent_speaking_end"})
                    await self._update_state("listening")
                    print(f"[{self.session_id}] Agent finished speaking")

        except Exception as e:
            print(f"Error processing TTS message: {e}")

    async def _on_tts_error(self, error):
        """TTS error handler"""
        print(f"[{self.session_id}] TTS error: {error}")

    async def _on_tts_close(self, *args):
        """TTS connection closed"""
        print(f"[{self.session_id}] TTS connection closed")

    # Helper methods

    def _calculate_audio_level(self, audio_data: bytes) -> int:
        """Calculate audio level (0-100) for waveform visualization"""
        if not audio_data:
            return 0

        # Simple RMS calculation
        import struct
        import math

        # Convert bytes to 16-bit integers
        samples = struct.unpack(f"<{len(audio_data)//2}h", audio_data)

        # Calculate RMS
        sum_squares = sum(s * s for s in samples)
        rms = math.sqrt(sum_squares / len(samples)) if samples else 0

        # Normalize to 0-100 (assuming 16-bit audio)
        level = min(100, int((rms / 32768) * 200))

        return level

    async def _send_audio_chunk(self, audio_data: bytes):
        """Send audio chunk to client"""
        self.tts_audio_sequence += 1
        await self.websocket.send_json({
            "type": "agent_audio_chunk",
            "data": list(audio_data),  # Convert bytes to list for JSON
            "sequence": self.tts_audio_sequence
        })

    async def _send_audio_level(self, source: str, level: int):
        """Send audio level for waveform visualization"""
        await self._send_message({
            "type": "audio_levels",
            "source": source,
            "level": level
        })

    async def _send_transcript_update(self, role: str, text: str, is_final: bool):
        """Send transcript update to client"""
        await self._send_message({
            "type": "transcript_update",
            "message": {
                "role": role,
                "text": text,
                "timestamp": int(time.time() * 1000),
                "isFinal": is_final
            }
        })

    async def _update_state(self, state: str):
        """Update and broadcast session state"""
        self.current_state = state
        await self._send_message({
            "type": "state_change",
            "state": state
        })

    async def _send_error(self, message: str):
        """Send error message to client"""
        await self._send_message({
            "type": "error",
            "message": message
        })

    async def _send_message(self, data: dict):
        """Send JSON message to client"""
        try:
            await self.websocket.send_json(data)
        except Exception as e:
            print(f"Error sending message: {e}")
