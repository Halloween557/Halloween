import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:speech_to_text/speech_recognition_result.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:uuid/uuid.dart';

void main() {
  runApp(const GideonApp());
}

class GideonApp extends StatelessWidget {
  const GideonApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'G.I.D.E.O.N.',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF080C14),
        colorScheme: const ColorScheme.dark(
          primary: Color(0xFF6366F1),
          secondary: Color(0xFF38BDF8),
          surface: Color(0xFF0F172A),
        ),
        fontFamily: 'Roboto',
      ),
      home: const ChatScreen(),
    );
  }
}

class Message {
  final String id;
  final String role;
  final String content;
  final DateTime createdAt;

  Message({
    required this.id,
    required this.role,
    required this.content,
    required this.createdAt,
  });

  factory Message.fromJson(Map<String, dynamic> json) {
    return Message(
      id: json['id']?.toString() ?? '',
      role: json['role'] ?? 'user',
      content: json['content'] ?? '',
      createdAt: DateTime.tryParse(json['created_at'] ?? '') ?? DateTime.now(),
    );
  }
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen>
    with SingleTickerProviderStateMixin {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<Message> _messages = [];

  // TTS & Audio
  final FlutterTts _flutterTts = FlutterTts();
  final AudioPlayer _audioPlayer = AudioPlayer();
  bool _voiceEnabled = true;
  bool _isSpeaking = false;
  String? _lastSpokenMessageId;

  // STT (Speech-to-Text / Mic)
  final SpeechToText _speechToText = SpeechToText();
  bool _sttAvailable = false;
  bool _isListening = false;
  String _micInterimText = '';
  late AnimationController _micPulseController;
  late Animation<double> _micPulseAnimation;

  // Configuration
  String _baseUrl = 'https://pc-agent-kristoffatabua-1396.vercel.app';
  String _agentToken = '1f73c44d-3e44-46dd-b707-d01c0c8be260';
  bool _isSending = false;
  bool _isPcOnline = false;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    _micPulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
    _micPulseAnimation = Tween<double>(begin: 1.0, end: 1.25).animate(
      CurvedAnimation(parent: _micPulseController, curve: Curves.easeInOut),
    );
    _initTts();
    _initStt();
    _loadConfig();
  }

  Future<void> _initTts() async {
    try {
      await _flutterTts.setLanguage("en-GB");
      await _flutterTts.setSpeechRate(0.48);
      await _flutterTts.setPitch(1.0);
      _flutterTts.setCompletionHandler(() {
        if (mounted) setState(() => _isSpeaking = false);
      });
      _audioPlayer.onPlayerComplete.listen((_) {
        if (mounted) setState(() => _isSpeaking = false);
      });
    } catch (_) {}
  }

  Future<void> _initStt() async {
    try {
      final available = await _speechToText.initialize(
        onError: (e) {
          if (mounted) {
            setState(() {
              _isListening = false;
              _micInterimText = '';
            });
            _micPulseController.stop();
            _micPulseController.reset();
          }
        },
        onStatus: (status) {
          if (status == 'done' || status == 'notListening') {
            if (mounted) {
              setState(() => _isListening = false);
              _micPulseController.stop();
              _micPulseController.reset();
              // Auto-send if we got something
              if (_controller.text.trim().isNotEmpty) {
                _sendMessage();
              }
            }
          }
        },
      );
      if (mounted) setState(() => _sttAvailable = available);
    } catch (_) {}
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _flutterTts.stop();
    _audioPlayer.dispose();
    _controller.dispose();
    _scrollController.dispose();
    _speechToText.cancel();
    _micPulseController.dispose();
    super.dispose();
  }

  Future<void> _loadConfig() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      _baseUrl = prefs.getString('api_base_url') ?? _baseUrl;
      _agentToken = prefs.getString('agent_token') ?? _agentToken;
      _voiceEnabled = prefs.getBool('voice_enabled') ?? true;
    });

    _fetchMessages(initial: true);
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) {
      if (mounted) _fetchMessages();
    });
  }

  Future<void> _saveConfig(String url, String token) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('api_base_url', url.trim());
    await prefs.setString('agent_token', token.trim());
    setState(() {
      _baseUrl = url.trim();
      _agentToken = token.trim();
    });
    _fetchMessages();
  }

  Future<void> _toggleVoice() async {
    final prefs = await SharedPreferences.getInstance();
    final next = !_voiceEnabled;
    await prefs.setBool('voice_enabled', next);
    if (!next) _stopSpeaking();
    setState(() => _voiceEnabled = next);
  }

  void _stopSpeaking() {
    _audioPlayer.stop();
    _flutterTts.stop();
    if (mounted) setState(() => _isSpeaking = false);
  }

  String _cleanTextForSpeech(String text) {
    return text
        .replaceAll(RegExp(r'```[\s\S]*?```'), 'Code block omitted.')
        .replaceAll(RegExp(r'`([^`]+)`'), r'$1')
        .replaceAll(RegExp(r'[*_#~]'), '')
        .replaceAll(RegExp(r'\[([^\]]+)\]\([^)]+\)'), r'$1')
        .replaceAll(RegExp(r'[🤖☁️⚠️🔴▶]'), '')
        .trim();
  }

  Future<void> _speakText(String text) async {
    if (!_voiceEnabled) return;
    final clean = _cleanTextForSpeech(text);
    if (clean.isEmpty) return;

    _stopSpeaking();
    if (mounted) setState(() => _isSpeaking = true);

    // 1. Try high-quality ElevenLabs British voice (same as web version)
    try {
      final ttsUri = Uri.parse('$_baseUrl/api/tts');
      final res = await http
          .post(
            ttsUri,
            headers: {
              'Authorization': 'Bearer $_agentToken',
              'Content-Type': 'application/json',
            },
            body: json.encode({'text': clean}),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200 && res.bodyBytes.isNotEmpty) {
        final tempDir = await getTemporaryDirectory();
        final file = File('${tempDir.path}/gideon_speech.mp3');
        await file.writeAsBytes(res.bodyBytes);
        await _audioPlayer.play(DeviceFileSource(file.path));
        return;
      }
    } catch (_) {
      // Fallback to native British TTS
    }

    // 2. Fallback: native Android TTS engine with British English
    try {
      await _flutterTts.speak(clean);
    } catch (_) {
      if (mounted) setState(() => _isSpeaking = false);
    }
  }

  // ── Microphone / STT ─────────────────────────────────────────────────────

  Future<void> _toggleMic() async {
    if (!_sttAvailable) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Speech recognition not available on this device.'),
        ),
      );
      return;
    }

    if (_isListening) {
      // Stop listening → auto-send handled in onStatus callback
      await _speechToText.stop();
      setState(() {
        _isListening = false;
        _micInterimText = '';
      });
      _micPulseController.stop();
      _micPulseController.reset();
      if (_controller.text.trim().isNotEmpty) {
        _sendMessage();
      }
      return;
    }

    // Pause TTS while recording
    _stopSpeaking();

    setState(() {
      _isListening = true;
      _micInterimText = '';
    });
    _micPulseController.repeat(reverse: true);

    await _speechToText.listen(
      onResult: (SpeechRecognitionResult result) {
        if (mounted) {
          setState(() {
            _controller.text = result.recognizedWords;
            _micInterimText = result.recognizedWords;
            _controller.selection = TextSelection.fromPosition(
              TextPosition(offset: _controller.text.length),
            );
          });
        }
      },
      listenFor: const Duration(seconds: 30),
      pauseFor: const Duration(seconds: 3),
      localeId: 'en_US',
      partialResults: true,
      listenOptions: SpeechListenOptions(cancelOnError: true),
    );
  }

  // ── Network ──────────────────────────────────────────────────────────────

  Future<void> _fetchMessages({bool initial = false}) async {
    if (_baseUrl.isEmpty || _agentToken.isEmpty) return;

    try {
      final uri = Uri.parse('$_baseUrl/api/messages');
      final res = await http.get(
        uri,
        headers: {'Authorization': 'Bearer $_agentToken'},
      ).timeout(const Duration(seconds: 4));

      if (res.statusCode == 200) {
        final data = json.decode(res.body);
        final List rawMsgs = data['messages'] ?? [];
        final device = data['device'] ?? {};

        final newMsgs = rawMsgs.map((m) => Message.fromJson(m)).toList();

        if (mounted) {
          final wasEmpty = _messages.isEmpty;
          final lastIdBefore =
              _messages.isNotEmpty ? _messages.last.id : null;

          setState(() {
            _isPcOnline = device['online'] == true;
            if (_messages.length != newMsgs.length ||
                (_messages.isNotEmpty &&
                    newMsgs.isNotEmpty &&
                    _messages.last.id != newMsgs.last.id)) {
              _messages.clear();
              _messages.addAll(newMsgs);
              _scrollToBottom();
            }
          });

          if (!initial && !wasEmpty && newMsgs.isNotEmpty) {
            final latest = newMsgs.last;
            if (latest.role == 'assistant' &&
                latest.id != lastIdBefore &&
                latest.id != _lastSpokenMessageId) {
              _lastSpokenMessageId = latest.id;
              _speakText(latest.content);
            }
          } else if (initial && newMsgs.isNotEmpty) {
            _lastSpokenMessageId = newMsgs.last.id;
          }
        }
      }
    } catch (_) {}
  }

  Future<void> _sendMessage() async {
    final text = _controller.text.trim();
    if (text.isEmpty || _isSending) return;

    _controller.clear();
    setState(() {
      _isSending = true;
      _micInterimText = '';
    });

    final clientId = const Uuid().v4();
    try {
      final uri = Uri.parse('$_baseUrl/api/messages');
      await http.post(
        uri,
        headers: {
          'Authorization': 'Bearer $_agentToken',
          'Content-Type': 'application/json',
        },
        body: json.encode({
          'message': text,
          'client_id': clientId,
        }),
      );
      await _fetchMessages();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error sending: $e')),
        );
      }
    } finally {
      if (mounted) setState(() => _isSending = false);
    }
  }

  Future<void> _clearChat() async {
    _stopSpeaking();
    try {
      final uri = Uri.parse('$_baseUrl/api/clear');
      await http.post(
        uri,
        headers: {'Authorization': 'Bearer $_agentToken'},
      );
      setState(() => _messages.clear());
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Error clearing chat: $e')),
        );
      }
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _showSettingsDialog() {
    final urlCtrl = TextEditingController(text: _baseUrl);
    final tokenCtrl = TextEditingController(text: _agentToken);

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1E293B),
        title: const Text('Gideon Connection Settings'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: urlCtrl,
              decoration: const InputDecoration(
                labelText: 'Server URL',
                hintText: 'https://...',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: tokenCtrl,
              decoration: const InputDecoration(
                labelText: 'Agent Token',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          ElevatedButton(
            onPressed: () {
              _saveConfig(urlCtrl.text, tokenCtrl.text);
              Navigator.pop(ctx);
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  Widget _buildMicButton() {
    return ScaleTransition(
      scale: _isListening ? _micPulseAnimation : const AlwaysStoppedAnimation(1.0),
      child: GestureDetector(
        onTap: _toggleMic,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          width: 48,
          height: 48,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: _isListening
                ? const Color(0xFFEF4444)
                : const Color(0xFF1E293B),
            border: Border.all(
              color: _isListening
                  ? const Color(0xFFEF4444)
                  : const Color(0xFF334155),
              width: 1.5,
            ),
            boxShadow: _isListening
                ? [
                    BoxShadow(
                      color: const Color(0xFFEF4444).withValues(alpha: 0.4),
                      blurRadius: 12,
                      spreadRadius: 2,
                    ),
                  ]
                : [],
          ),
          child: Icon(
            _isListening ? Icons.mic : Icons.mic_none_outlined,
            color: _isListening ? Colors.white : Colors.white54,
            size: 22,
          ),
        ),
      ),
    );
  }

  Widget _buildInputBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: const BoxDecoration(
        color: Color(0xFF0F172A),
        border: Border(
          top: BorderSide(color: Color(0xFF1E293B)),
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Interim speech text preview
          if (_isListening && _micInterimText.isNotEmpty)
            Container(
              width: double.infinity,
              margin: const EdgeInsets.only(bottom: 8),
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              decoration: BoxDecoration(
                color: const Color(0xFF1E293B),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                    color: const Color(0xFFEF4444).withValues(alpha: 0.4)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.graphic_eq,
                      color: Color(0xFFEF4444), size: 16),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      _micInterimText,
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 13,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          Row(
            children: [
              // Mic button
              _buildMicButton(),
              const SizedBox(width: 8),
              // Text field
              Expanded(
                child: Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF1E293B),
                    borderRadius: BorderRadius.circular(24),
                    border: Border.all(color: const Color(0xFF334155)),
                  ),
                  child: TextField(
                    controller: _controller,
                    textInputAction: TextInputAction.send,
                    onSubmitted: (_) => _sendMessage(),
                    decoration: InputDecoration(
                      hintText: _isListening
                          ? 'Listening...'
                          : 'Ask Gideon anything...',
                      hintStyle: TextStyle(
                        color: _isListening
                            ? const Color(0xFFEF4444).withValues(alpha: 0.6)
                            : Colors.white38,
                      ),
                      border: InputBorder.none,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 18,
                        vertical: 12,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              // Send button
              Container(
                decoration: const BoxDecoration(
                  color: Color(0xFF4F46E5),
                  shape: BoxShape.circle,
                ),
                child: IconButton(
                  icon: _isSending
                      ? const SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white,
                          ),
                        )
                      : const Icon(Icons.arrow_upward, color: Colors.white),
                  onPressed: _isSending ? null : _sendMessage,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        backgroundColor: const Color(0xFF0F172A),
        elevation: 0,
        title: Row(
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(
                color: _isPcOnline ? Colors.greenAccent : Colors.amber,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: (_isPcOnline ? Colors.greenAccent : Colors.amber)
                        .withValues(alpha: 0.5),
                    blurRadius: 6,
                  )
                ],
              ),
            ),
            const SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'G.I.D.E.O.N.',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5,
                  ),
                ),
                Text(
                  _isPcOnline ? 'PC Online (Active)' : 'Standby / Cloud',
                  style: TextStyle(
                    fontSize: 11,
                    color: _isPcOnline ? Colors.greenAccent : Colors.white70,
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          // Voice on/off
          IconButton(
            icon: Icon(
              _voiceEnabled
                  ? (_isSpeaking ? Icons.volume_up : Icons.volume_up_outlined)
                  : Icons.volume_off_outlined,
              color: _voiceEnabled
                  ? (_isSpeaking ? Colors.greenAccent : Colors.white70)
                  : Colors.white30,
            ),
            tooltip: _voiceEnabled ? 'Mute Voice' : 'Enable Voice',
            onPressed: _toggleVoice,
          ),
          IconButton(
            icon: const Icon(Icons.delete_sweep_outlined, color: Colors.white70),
            tooltip: 'Clear Chat',
            onPressed: _clearChat,
          ),
          IconButton(
            icon: const Icon(Icons.settings_outlined, color: Colors.white70),
            tooltip: 'Settings',
            onPressed: _showSettingsDialog,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: _messages.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            Icons.auto_awesome,
                            size: 52,
                            color: Theme.of(context).colorScheme.primary,
                          ),
                          const SizedBox(height: 16),
                          const Text(
                            'G.I.D.E.O.N.',
                            style: TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 2,
                            ),
                          ),
                          const SizedBox(height: 8),
                          const Padding(
                            padding: EdgeInsets.symmetric(horizontal: 36),
                            child: Text(
                              'Tap the mic or type to command your PC.\n"Check emails" · "List WhatsApp chats" · "Search flights"',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                color: Colors.white54,
                                height: 1.5,
                              ),
                            ),
                          ),
                        ],
                      ),
                    )
                  : ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 16,
                        vertical: 12,
                      ),
                      itemCount: _messages.length,
                      itemBuilder: (context, index) {
                        final m = _messages[index];
                        final isUser = m.role == 'user';
                        return Align(
                          alignment: isUser
                              ? Alignment.centerRight
                              : Alignment.centerLeft,
                          child: Container(
                            margin: const EdgeInsets.symmetric(vertical: 6),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 16,
                              vertical: 12,
                            ),
                            constraints: BoxConstraints(
                              maxWidth:
                                  MediaQuery.of(context).size.width * 0.82,
                            ),
                            decoration: BoxDecoration(
                              color: isUser
                                  ? const Color(0xFF4F46E5)
                                  : const Color(0xFF1E293B),
                              borderRadius: BorderRadius.only(
                                topLeft: const Radius.circular(16),
                                topRight: const Radius.circular(16),
                                bottomLeft:
                                    Radius.circular(isUser ? 16 : 4),
                                bottomRight:
                                    Radius.circular(isUser ? 4 : 16),
                              ),
                              border: Border.all(
                                color: isUser
                                    ? Colors.transparent
                                    : const Color(0xFF334155),
                              ),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                SelectableText(
                                  m.content,
                                  style: const TextStyle(
                                    fontSize: 14.5,
                                    height: 1.4,
                                    color: Colors.white,
                                  ),
                                ),
                                if (!isUser) ...[
                                  const SizedBox(height: 6),
                                  Align(
                                    alignment: Alignment.centerRight,
                                    child: GestureDetector(
                                      onTap: () => _speakText(m.content),
                                      child: const Icon(
                                        Icons.volume_up_outlined,
                                        size: 18,
                                        color: Colors.white38,
                                      ),
                                    ),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        );
                      },
                    ),
            ),
            _buildInputBar(),
          ],
        ),
      ),
    );
  }
}
