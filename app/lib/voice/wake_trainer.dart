import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:material_symbols_icons/symbols.dart';

import '../core/api.dart';
import '../l10n/strings.dart';
import '../theme.dart';
import '../widgets/overlays.dart';
import '../widgets/sora_widgets.dart';
import 'voice_input.dart';
import 'wake_service.dart';

/// Settings → Voice → "Teach Sora your voice": records the owner saying "Hey Sora" (and, after that,
/// things that are not "Hey Sora") through this device's microphone, the way the background
/// listener hears it, and keeps each clip on the server (data/wakeword/recorded) for training the
/// on-device wake-word model.
class WakeTrainer extends StatefulWidget {
  const WakeTrainer({super.key, required this.api});

  final SoraApi api;

  @override
  State<WakeTrainer> createState() => _WakeTrainerState();
}

/// What to say: the phrase in quotes (or null for free speech) and how to say it.
typedef _Prompt = ({String? phrase, String en, String bn});

const _positiveGoal = 50, _negativeGoal = 25;

const List<_Prompt> _positives = [
  (phrase: 'Hey Sora', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'Hey Sora', en: 'quietly', bn: 'আস্তে'),
  (phrase: 'Sora', en: 'just the name', bn: 'শুধু নামটা'),
  (phrase: 'Hey Sora', en: 'a bit louder', bn: 'একটু জোরে'),
  (phrase: 'Hey Sora', en: 'quickly', bn: 'তাড়াতাড়ি'),
  (phrase: 'Hey Sora', en: 'from 2–3 metres away', bn: '২–৩ মিটার দূর থেকে'),
  (phrase: 'Sora', en: 'slowly', bn: 'ধীরে'),
  (phrase: 'Hey Sora', en: 'as if calling from another room', bn: 'অন্য ঘর থেকে ডাকার মতো'),
  (phrase: 'Hey Sora', en: 'tired or sleepy', bn: 'ক্লান্ত বা ঘুম-ঘুম গলায়'),
  (phrase: 'Sora', en: 'as if asking a question', bn: 'প্রশ্ন করার মতো'),
];

const List<_Prompt> _negatives = [
  (phrase: 'Hey Siri', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'Sorry', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'Hey Sara', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'সোনা', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'Story', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'সারা দিন', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'Hey Google', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: 'সরো তো', en: 'normally', bn: 'স্বাভাবিকভাবে'),
  (phrase: null, en: 'any sentence in Bangla', bn: 'বাংলায় যেকোনো একটা বাক্য'),
  (phrase: null, en: 'any sentence in English', bn: 'ইংরেজিতে যেকোনো একটা বাক্য'),
  (phrase: null, en: 'count from one to five', bn: 'এক থেকে পাঁচ পর্যন্ত গুনুন'),
  (phrase: null, en: 'a few words about your day', bn: 'আপনার দিন নিয়ে দু-এক কথা'),
];

class _WakeTrainerState extends State<WakeTrainer> {
  VoiceRecorder? _rec;
  bool _open = false, _busy = false;
  double _level = 0;
  int _p = 0, _n = 0; // this device's recordings
  String? _note;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _stop();
    super.dispose();
  }

  bool get _positive => _p < _positiveGoal || _n >= _negativeGoal;
  _Prompt get _prompt => _positive ? _positives[_p % _positives.length] : _negatives[_n % _negatives.length];

  void _counts(Map<String, dynamic> c) {
    if (!mounted) return;
    setState(() {
      _p = (c['positive'] as Map)['this_device'] as int? ?? 0;
      _n = (c['negative'] as Map)['this_device'] as int? ?? 0;
    });
  }

  Future<void> _load() async {
    try {
      _counts(await widget.api.wakeSamples());
    } catch (_) {}
  }

  Future<void> _record() async {
    if (_busy) return;
    final kind = _positive ? 'positive' : 'negative';
    final rec = VoiceRecorder(
      raw: true,
      silence: const Duration(milliseconds: 600),
      noSpeech: const Duration(seconds: 5),
      maxLength: Duration(seconds: kind == 'positive' ? 4 : 7),
    );
    if (!await rec.hasPermission()) {
      if (mounted) showToast(context, S.of(context).handsFreeDenied);
      return;
    }
    WakeService.pause(); // two recorders would fight over the phone's mic
    setState(() {
      _busy = true;
      _rec = rec;
      _note = null;
    });
    Endpoint how;
    Uint8List? wav;
    try {
      final ended = Completer<Endpoint>();
      await rec.start(
        onLevel: (l) {
          if (mounted) setState(() => _level = l);
        },
        onEnd: (e) {
          if (!ended.isCompleted) ended.complete(e);
        },
      );
      how = await ended.future;
      wav = await rec.stop();
    } catch (e) {
      if (mounted) setState(() => _note = S.of(context).micProblem('$e'));
      return;
    } finally {
      await _stop();
    }
    if (!mounted) return;
    final s = S.of(context);
    if (how == Endpoint.noSpeech || wav == null) {
      setState(() => _note = s.teachNothing);
      return;
    }
    try {
      _counts(await widget.api.addWakeSample(wav, kind));
      if (mounted) setState(() => _note = s.teachSaved);
    } catch (e) {
      if (mounted) setState(() => _note = e.toString());
    }
  }

  Future<void> _stop() async {
    final rec = _rec;
    _rec = null;
    if (rec != null) {
      await rec.dispose();
      WakeService.resume();
    }
    if (mounted) {
      setState(() {
        _busy = false;
        _level = 0;
      });
    }
  }

  Future<void> _undo() async {
    try {
      _counts(await widget.api.undoWakeSample());
      if (mounted) setState(() => _note = null);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) {
    final p = SoraPalette.of(context);
    final s = S.of(context);
    final done = _p >= _positiveGoal && _n >= _negativeGoal;
    final prompt = _prompt;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(s.teachVoice, style: SoraType.ui(14, weight: FontWeight.w500, color: p.ink, height: 1.4)),
                    const SizedBox(height: 4),
                    Text(
                      _open ? s.teachCount(_p, _positiveGoal, _n, _negativeGoal) : s.teachVoiceHint,
                      style: SoraType.ui(12.5, color: p.dim, height: 1.45),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 12),
              GlassButton(
                label: _open ? s.done : s.teachStart,
                height: 36,
                radius: 12,
                fontSize: 13.5,
                onTap: _busy
                    ? null
                    : () {
                        setState(() => _open = !_open);
                        if (_open) _load();
                      },
              ),
            ],
          ),
          if (_open) ...[
            const SizedBox(height: 16),
            if (done)
              Text(s.teachAllDone, textAlign: TextAlign.center, style: SoraType.ui(13.5, color: p.ok, height: 1.45))
            else if (!_positive)
              Text(s.teachOtherPhase, textAlign: TextAlign.center, style: SoraType.ui(12.5, color: p.dim, height: 1.45)),
            const SizedBox(height: 10),
            Text(
              prompt.phrase == null ? (s.isBn ? prompt.bn : prompt.en) : '${s.teachSay} “${prompt.phrase}”',
              textAlign: TextAlign.center,
              style: SoraType.ui(20, weight: FontWeight.w600, color: p.ink, height: 1.3),
            ),
            if (prompt.phrase != null) ...[
              const SizedBox(height: 4),
              Text(
                s.isBn ? prompt.bn : prompt.en,
                textAlign: TextAlign.center,
                style: SoraType.ui(13.5, color: p.acc, height: 1.4),
              ),
            ],
            const SizedBox(height: 16),
            Center(
              child: Pressable(
                onTap: _busy ? null : _record,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 90),
                  width: 72,
                  height: 72,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: _busy ? p.acc : p.surf2,
                    boxShadow: _busy ? [BoxShadow(color: p.acc.withValues(alpha: .5), blurRadius: 8 + 28 * _level)] : null,
                  ),
                  child: Center(
                    child: LIcon(Symbols.mic_rounded, size: 30, color: _busy ? Colors.white : p.ink, fill: _busy),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Text(
              _busy ? s.statusListening : (_note ?? s.teachTap),
              textAlign: TextAlign.center,
              style: SoraType.ui(12.5, color: _note == s.teachSaved ? p.ok : p.dim, height: 1.4),
            ),
            if (_p + _n > 0 && !_busy) ...[
              const SizedBox(height: 6),
              Center(
                child: TextButton.icon(
                  onPressed: _undo,
                  icon: LIcon(Symbols.undo_rounded, size: 17, color: p.dim),
                  label: Text(s.teachUndo, style: SoraType.ui(12.5, color: p.dim)),
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }
}
