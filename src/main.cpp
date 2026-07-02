#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_set>
#include <utility>
#include <vector>

#if EDGEVOICE_HAS_ALSA
#include <alsa/asoundlib.h>
#endif

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

using Clock = std::chrono::steady_clock;
using TimePoint = Clock::time_point;

namespace {

struct Options {
  std::string scenario = "mixed_vi_en";
  std::string custom_text;
  std::string audio = "null";
  std::string alsa_device = "default";
  std::string wav_path = "benchmark_results/out.wav";
  std::string out_path;
  int iterations = 1;
  int sample_rate = 24000;
  int channels = 1;
  int period_ms = 20;
  int buffer_ms = 120;
  int jitter_ms = 60;
  int asr_partial_ms = 35;
  int asr_words_per_partial = 2;
  int tts_first_chunk_ms = 80;
  int tts_chunk_ms = 40;
  int tts_inter_chunk_gap_ms = 22;
  int tts_chunks_per_segment = 6;
  int split_min_tokens = 4;
  int split_max_tokens = 16;
  int barge_in_ms = 0;
  bool verbose = false;

  int frames_per_chunk() const {
    return std::max(1, sample_rate * tts_chunk_ms / 1000);
  }

  int jitter_frames() const {
    return std::max(1, sample_rate * jitter_ms / 1000);
  }
};

std::string trim(const std::string& value) {
  const auto first = value.find_first_not_of(" \t\r\n");
  if (first == std::string::npos) {
    return "";
  }
  const auto last = value.find_last_not_of(" \t\r\n");
  return value.substr(first, last - first + 1);
}

std::string collapse_spaces(const std::string& value) {
  std::string out;
  bool previous_space = false;
  for (unsigned char ch : value) {
    const bool is_space = ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n';
    if (is_space) {
      if (!previous_space && !out.empty()) {
        out.push_back(' ');
      }
      previous_space = true;
    } else {
      out.push_back(static_cast<char>(ch));
      previous_space = false;
    }
  }
  return trim(out);
}

std::string json_escape(const std::string& value) {
  std::ostringstream out;
  for (unsigned char ch : value) {
    switch (ch) {
      case '\\':
        out << "\\\\";
        break;
      case '"':
        out << "\\\"";
        break;
      case '\n':
        out << "\\n";
        break;
      case '\r':
        out << "\\r";
        break;
      case '\t':
        out << "\\t";
        break;
      default:
        if (ch < 0x20) {
          out << "\\u" << std::hex << std::setw(4) << std::setfill('0')
              << static_cast<int>(ch) << std::dec;
        } else {
          out << static_cast<char>(ch);
        }
    }
  }
  return out.str();
}

double elapsed_ms(TimePoint start, TimePoint end) {
  return std::chrono::duration<double, std::milli>(end - start).count();
}

bool starts_with(const std::string& value, const std::string& prefix) {
  return value.rfind(prefix, 0) == 0;
}

int parse_int(const std::string& name, const std::string& value) {
  try {
    size_t consumed = 0;
    int parsed = std::stoi(value, &consumed);
    if (consumed != value.size()) {
      throw std::invalid_argument("trailing input");
    }
    return parsed;
  } catch (const std::exception&) {
    throw std::runtime_error("Invalid integer for " + name + ": " + value);
  }
}

void print_help(const char* program) {
  std::cout
      << "Usage: " << program << " [options]\n"
      << "\n"
      << "Core options:\n"
      << "  --audio=null|wav|alsa          Audio backend. Default: null\n"
      << "  --iterations=N                 Benchmark iterations. Default: 1\n"
      << "  --out=PATH                     Append JSONL metrics to PATH\n"
      << "  --scenario=mixed_vi_en         Scenario name. Default: mixed_vi_en\n"
      << "  --text=TEXT                    Override scenario text\n"
      << "\n"
      << "Timing options:\n"
      << "  --period-ms=N                  ALSA/audio period in ms. Default: 20\n"
      << "  --buffer-ms=N                  ALSA/audio buffer in ms. Default: 120\n"
      << "  --jitter-ms=N                  Initial jitter prebuffer in ms. Default: 60\n"
      << "  --asr-partial-ms=N             Delay between ASR partial updates. Default: 35\n"
      << "  --tts-first-chunk-ms=N         Simulated TTS first chunk latency. Default: 80\n"
      << "  --tts-inter-chunk-gap-ms=N     Delay between generated PCM chunks. Default: 22\n"
      << "  --split-min-tokens=N           Minimum tokens before emitting a segment. Default: 4\n"
      << "  --split-max-tokens=N           Force a soft split after this many tokens. Default: 16\n"
      << "  --barge-in-ms=N                Trigger interruption after N ms. Default: 0\n"
      << "\n"
      << "Native audio options:\n"
      << "  --alsa-device=NAME             ALSA PCM device. Default: default\n"
      << "  --wav-path=PATH                WAV file when --audio=wav\n";
}

Options parse_options(int argc, char** argv) {
  Options opts;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--help" || arg == "-h") {
      print_help(argv[0]);
      std::exit(0);
    } else if (arg == "--verbose") {
      opts.verbose = true;
    } else if (starts_with(arg, "--audio=")) {
      opts.audio = arg.substr(8);
    } else if (starts_with(arg, "--iterations=")) {
      opts.iterations = parse_int("--iterations", arg.substr(13));
    } else if (starts_with(arg, "--out=")) {
      opts.out_path = arg.substr(6);
    } else if (starts_with(arg, "--scenario=")) {
      opts.scenario = arg.substr(11);
    } else if (starts_with(arg, "--text=")) {
      opts.custom_text = arg.substr(7);
    } else if (starts_with(arg, "--sample-rate=")) {
      opts.sample_rate = parse_int("--sample-rate", arg.substr(14));
    } else if (starts_with(arg, "--period-ms=")) {
      opts.period_ms = parse_int("--period-ms", arg.substr(12));
    } else if (starts_with(arg, "--buffer-ms=")) {
      opts.buffer_ms = parse_int("--buffer-ms", arg.substr(12));
    } else if (starts_with(arg, "--jitter-ms=")) {
      opts.jitter_ms = parse_int("--jitter-ms", arg.substr(12));
    } else if (starts_with(arg, "--asr-partial-ms=")) {
      opts.asr_partial_ms = parse_int("--asr-partial-ms", arg.substr(17));
    } else if (starts_with(arg, "--asr-words-per-partial=")) {
      opts.asr_words_per_partial = parse_int("--asr-words-per-partial", arg.substr(24));
    } else if (starts_with(arg, "--tts-first-chunk-ms=")) {
      opts.tts_first_chunk_ms = parse_int("--tts-first-chunk-ms", arg.substr(21));
    } else if (starts_with(arg, "--tts-chunk-ms=")) {
      opts.tts_chunk_ms = parse_int("--tts-chunk-ms", arg.substr(15));
    } else if (starts_with(arg, "--tts-inter-chunk-gap-ms=")) {
      opts.tts_inter_chunk_gap_ms = parse_int("--tts-inter-chunk-gap-ms", arg.substr(25));
    } else if (starts_with(arg, "--tts-chunks-per-segment=")) {
      opts.tts_chunks_per_segment = parse_int("--tts-chunks-per-segment", arg.substr(25));
    } else if (starts_with(arg, "--split-min-tokens=")) {
      opts.split_min_tokens = parse_int("--split-min-tokens", arg.substr(19));
    } else if (starts_with(arg, "--split-max-tokens=")) {
      opts.split_max_tokens = parse_int("--split-max-tokens", arg.substr(19));
    } else if (starts_with(arg, "--barge-in-ms=")) {
      opts.barge_in_ms = parse_int("--barge-in-ms", arg.substr(14));
    } else if (starts_with(arg, "--alsa-device=")) {
      opts.alsa_device = arg.substr(14);
    } else if (starts_with(arg, "--wav-path=")) {
      opts.wav_path = arg.substr(11);
    } else {
      throw std::runtime_error("Unknown option: " + arg);
    }
  }

  if (opts.audio != "null" && opts.audio != "wav" && opts.audio != "alsa") {
    throw std::runtime_error("--audio must be one of: null, wav, alsa");
  }
  if (opts.iterations < 1) {
    throw std::runtime_error("--iterations must be >= 1");
  }
  if (opts.channels != 1) {
    throw std::runtime_error("This benchmark scaffold currently emits mono PCM only");
  }
  if (opts.split_min_tokens < 1 || opts.split_max_tokens < opts.split_min_tokens) {
    throw std::runtime_error("--split-max-tokens must be >= --split-min-tokens >= 1");
  }
  return opts;
}

std::string scenario_text(const Options& opts) {
  if (!opts.custom_text.empty()) {
    return opts.custom_text;
  }
  if (opts.scenario == "mixed_vi_en") {
    return "Tăng moment xoắn cho cụm rotary actuator ở khớp gối lên 15 phần trăm, đồng thời check lại sensor vision giúp anh.";
  }
  if (opts.scenario == "barge_in") {
    return "Robot đang báo cáo trạng thái pin, nhiệt độ actuator, torque limit, và chuẩn bị tiếp tục phân tích sensor vision.";
  }
  throw std::runtime_error("Unknown scenario: " + opts.scenario);
}

template <typename T>
class BlockingQueue {
 public:
  enum class PopResult { Item, Timeout, Closed };

  bool push(T item) {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      if (closed_) {
        return false;
      }
      queue_.push_back(std::move(item));
    }
    cv_.notify_one();
    return true;
  }

  bool pop(T& out) {
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [&] { return closed_ || !queue_.empty(); });
    if (queue_.empty()) {
      return false;
    }
    out = std::move(queue_.front());
    queue_.pop_front();
    return true;
  }

  PopResult pop_for(T& out, std::chrono::milliseconds timeout) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (!cv_.wait_for(lock, timeout, [&] { return closed_ || !queue_.empty(); })) {
      return PopResult::Timeout;
    }
    if (queue_.empty()) {
      return PopResult::Closed;
    }
    out = std::move(queue_.front());
    queue_.pop_front();
    return PopResult::Item;
  }

  void clear() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      queue_.clear();
    }
    cv_.notify_all();
  }

  void close() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      closed_ = true;
    }
    cv_.notify_all();
  }

 private:
  std::mutex mutex_;
  std::condition_variable cv_;
  std::deque<T> queue_;
  bool closed_ = false;
};

struct TextJob {
  int segment_id = 0;
  int epoch = 0;
  std::string text;
  TimePoint boundary_time;
};

struct PcmChunk {
  int segment_id = 0;
  int epoch = 0;
  bool first_for_segment = false;
  TimePoint boundary_time;
  std::vector<int16_t> samples;
  int frames = 0;
};

class SentenceSplitter {
 public:
  SentenceSplitter(int min_tokens, int max_tokens)
      : min_tokens_(std::max(1, min_tokens)),
        max_tokens_(std::max(std::max(1, min_tokens), max_tokens)) {}

  std::vector<std::string> process_partial(const std::string& partial) {
    const std::string normalized = collapse_spaces(partial);
    if (normalized.empty()) {
      last_partial_ = normalized;
      return {};
    }

    reconcile_partial_correction(normalized);

    std::vector<std::string> segments;
    while (emitted_pos_ < normalized.size()) {
      const size_t hard_boundary = find_hard_boundary(normalized, emitted_pos_);
      if (hard_boundary != std::string::npos) {
        const std::string segment =
            trim(normalized.substr(emitted_pos_, hard_boundary - emitted_pos_ + 1));
        if (token_count(segment) >= min_tokens_ || hard_boundary + 1 == normalized.size()) {
          emit_segment(segment, segments);
          emitted_pos_ = skip_spaces(normalized, hard_boundary + 1);
          continue;
        }
        break;
      }

      const std::string pending = trim(normalized.substr(emitted_pos_));
      if (token_count(pending) >= max_tokens_) {
        const size_t cut = find_soft_boundary_or_token_limit(normalized, emitted_pos_, max_tokens_);
        emit_segment(trim(normalized.substr(emitted_pos_, cut - emitted_pos_)), segments);
        emitted_pos_ = skip_spaces(normalized, cut);
        continue;
      }

      break;
    }

    last_partial_ = normalized;
    return segments;
  }

  std::vector<std::string> flush() {
    std::vector<std::string> segments;
    if (emitted_pos_ < last_partial_.size()) {
      const std::string segment = trim(last_partial_.substr(emitted_pos_));
      emit_segment(segment, segments);
    }
    emitted_pos_ = last_partial_.size();
    return segments;
  }

 private:
  static size_t common_prefix_len(const std::string& a, const std::string& b) {
    const size_t limit = std::min(a.size(), b.size());
    size_t i = 0;
    while (i < limit && a[i] == b[i]) {
      ++i;
    }
    return i;
  }

  static bool is_hard_boundary(char ch) {
    return ch == ',' || ch == '.' || ch == '?' || ch == '!' || ch == ';' || ch == ':';
  }

  static size_t find_hard_boundary(const std::string& text, size_t start) {
    for (size_t i = start; i < text.size(); ++i) {
      if (is_hard_boundary(text[i])) {
        return i;
      }
    }
    return std::string::npos;
  }

  static size_t skip_spaces(const std::string& text, size_t pos) {
    while (pos < text.size() && text[pos] == ' ') {
      ++pos;
    }
    return pos;
  }

  static int token_count(const std::string& text) {
    std::istringstream input(text);
    int count = 0;
    std::string token;
    while (input >> token) {
      ++count;
    }
    return count;
  }

  static size_t token_limit_boundary(const std::string& text, size_t start, int token_limit) {
    int tokens = 0;
    bool in_token = false;
    for (size_t i = start; i < text.size(); ++i) {
      if (text[i] == ' ') {
        if (in_token) {
          ++tokens;
          if (tokens >= token_limit) {
            return i;
          }
        }
        in_token = false;
      } else {
        in_token = true;
      }
    }
    return text.size();
  }

  static size_t find_soft_boundary_or_token_limit(const std::string& text,
                                                  size_t start,
                                                  int token_limit) {
    const size_t hard_cut = token_limit_boundary(text, start, token_limit);
    size_t best = hard_cut;
    const std::vector<std::string> markers = {
        " đồng thời ", " sau đó ", " rồi ", " và ", " and ", " then "};

    for (const auto& marker : markers) {
      size_t pos = text.find(marker, start);
      while (pos != std::string::npos && pos < hard_cut) {
        const size_t candidate = pos + marker.size();
        if (candidate > start) {
          best = std::max(best == hard_cut ? candidate : best, candidate);
        }
        pos = text.find(marker, pos + 1);
      }
    }
    return std::min(best, text.size());
  }

  void emit_segment(const std::string& segment, std::vector<std::string>& out) {
    const std::string normalized = collapse_spaces(segment);
    if (!normalized.empty() && emitted_segments_.insert(normalized).second) {
      out.push_back(normalized);
    }
  }

  void reconcile_partial_correction(const std::string& normalized) {
    if (last_partial_.empty()) {
      return;
    }
    const size_t common = common_prefix_len(normalized, last_partial_);
    if (common < emitted_pos_) {
      // Already emitted audio cannot be retracted, so keep the committed byte offset
      // and only resume when ASR produces text beyond it.
      emitted_pos_ = std::min(emitted_pos_, normalized.size());
    }
    if (normalized.size() < emitted_pos_) {
      emitted_pos_ = normalized.size();
    }
  }

  std::string last_partial_;
  std::unordered_set<std::string> emitted_segments_;
  size_t emitted_pos_ = 0;
  int min_tokens_ = 4;
  int max_tokens_ = 16;
};

struct RunState {
  std::atomic<int> epoch{0};
  std::atomic<bool> flush_requested{false};
};

class Metrics {
 public:
  explicit Metrics(int iteration) : iteration_(iteration), start_(Clock::now()) {}

  void mark_segment(const TextJob& job) {
    std::lock_guard<std::mutex> lock(mutex_);
    ++segments_;
    segment_text_[job.segment_id] = job.text;
    segment_boundary_[job.segment_id] = job.boundary_time;
  }

  void mark_pcm_chunk() {
    std::lock_guard<std::mutex> lock(mutex_);
    ++pcm_chunks_;
  }

  void mark_underrun() {
    std::lock_guard<std::mutex> lock(mutex_);
    ++underruns_;
  }

  void mark_playback_start(const PcmChunk& chunk, int sample_rate) {
    const auto now = Clock::now();
    const double duration_ms = 1000.0 * static_cast<double>(chunk.frames) / sample_rate;

    std::lock_guard<std::mutex> lock(mutex_);
    if (expected_next_audio_.time_since_epoch().count() != 0) {
      max_audio_gap_ms_ = std::max(max_audio_gap_ms_, elapsed_ms(expected_next_audio_, now));
    }
    expected_next_audio_ = now + std::chrono::duration_cast<Clock::duration>(
                                     std::chrono::duration<double, std::milli>(duration_ms));

    if (chunk.first_for_segment && first_played_segment_ids_.insert(chunk.segment_id).second) {
      const auto boundary = segment_boundary_.find(chunk.segment_id);
      if (boundary != segment_boundary_.end()) {
        ttft_values_ms_.push_back(elapsed_ms(boundary->second, now));
      }
    }
  }

  void mark_barge_request() {
    std::lock_guard<std::mutex> lock(mutex_);
    barge_requested_ = Clock::now();
  }

  void mark_barge_flushed() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (barge_requested_.time_since_epoch().count() != 0 &&
        barge_flushed_.time_since_epoch().count() == 0) {
      barge_flushed_ = Clock::now();
    }
  }

  std::string to_json(const Options& opts, const std::string& status) const {
    std::lock_guard<std::mutex> lock(mutex_);
    const auto end = Clock::now();
    const double total_ms = elapsed_ms(start_, end);
    const double ttft_avg = ttft_values_ms_.empty()
                                ? -1.0
                                : std::accumulate(ttft_values_ms_.begin(), ttft_values_ms_.end(), 0.0) /
                                      static_cast<double>(ttft_values_ms_.size());
    const double ttft_min = ttft_values_ms_.empty()
                                ? -1.0
                                : *std::min_element(ttft_values_ms_.begin(), ttft_values_ms_.end());
    const double ttft_max = ttft_values_ms_.empty()
                                ? -1.0
                                : *std::max_element(ttft_values_ms_.begin(), ttft_values_ms_.end());
    const double barge_reaction_ms =
        (barge_requested_.time_since_epoch().count() != 0 &&
         barge_flushed_.time_since_epoch().count() != 0)
            ? elapsed_ms(barge_requested_, barge_flushed_)
            : -1.0;

    std::ostringstream out;
    out << std::fixed << std::setprecision(3);
    out << "{";
    out << "\"status\":\"" << json_escape(status) << "\",";
    out << "\"iteration\":" << iteration_ << ",";
    out << "\"scenario\":\"" << json_escape(opts.scenario) << "\",";
    out << "\"audio\":\"" << json_escape(opts.audio) << "\",";
    out << "\"sample_rate\":" << opts.sample_rate << ",";
    out << "\"period_ms\":" << opts.period_ms << ",";
    out << "\"buffer_ms\":" << opts.buffer_ms << ",";
    out << "\"jitter_ms\":" << opts.jitter_ms << ",";
    out << "\"asr_partial_ms\":" << opts.asr_partial_ms << ",";
    out << "\"tts_first_chunk_ms\":" << opts.tts_first_chunk_ms << ",";
    out << "\"tts_inter_chunk_gap_ms\":" << opts.tts_inter_chunk_gap_ms << ",";
    out << "\"split_min_tokens\":" << opts.split_min_tokens << ",";
    out << "\"split_max_tokens\":" << opts.split_max_tokens << ",";
    out << "\"segments\":" << segments_ << ",";
    out << "\"pcm_chunks\":" << pcm_chunks_ << ",";
    out << "\"underruns\":" << underruns_ << ",";
    out << "\"ttft_count\":" << ttft_values_ms_.size() << ",";
    out << "\"ttft_min_ms\":" << ttft_min << ",";
    out << "\"ttft_avg_ms\":" << ttft_avg << ",";
    out << "\"ttft_max_ms\":" << ttft_max << ",";
    out << "\"max_audio_gap_ms\":" << std::max(0.0, max_audio_gap_ms_) << ",";
    out << "\"barge_in_reaction_ms\":" << barge_reaction_ms << ",";
    out << "\"total_ms\":" << total_ms;
    out << "}";
    return out.str();
  }

 private:
  int iteration_ = 0;
  TimePoint start_;
  mutable std::mutex mutex_;
  int segments_ = 0;
  int pcm_chunks_ = 0;
  int underruns_ = 0;
  double max_audio_gap_ms_ = 0.0;
  TimePoint expected_next_audio_{};
  TimePoint barge_requested_{};
  TimePoint barge_flushed_{};
  std::map<int, std::string> segment_text_;
  std::map<int, TimePoint> segment_boundary_;
  std::unordered_set<int> first_played_segment_ids_;
  std::vector<double> ttft_values_ms_;
};

std::vector<std::string> make_partials(const std::string& text, int words_per_partial) {
  std::istringstream input(text);
  std::vector<std::string> partials;
  std::string word;
  std::string current;
  int words_since_emit = 0;

  while (input >> word) {
    if (!current.empty()) {
      current += " ";
    }
    current += word;
    ++words_since_emit;

    const bool punctuation = word.find(',') != std::string::npos ||
                             word.find('.') != std::string::npos ||
                             word.find('?') != std::string::npos ||
                             word.find('!') != std::string::npos;
    if (words_since_emit >= std::max(1, words_per_partial) || punctuation) {
      partials.push_back(current);
      words_since_emit = 0;
    }
  }

  if (partials.empty() || partials.back() != current) {
    partials.push_back(current);
  }
  return partials;
}

PcmChunk generate_pcm_chunk(const Options& opts, const TextJob& job, int index) {
  PcmChunk chunk;
  chunk.segment_id = job.segment_id;
  chunk.epoch = job.epoch;
  chunk.first_for_segment = index == 0;
  chunk.boundary_time = job.boundary_time;
  chunk.frames = opts.frames_per_chunk();
  chunk.samples.resize(static_cast<size_t>(chunk.frames * opts.channels));

  const double frequency = 220.0 + 15.0 * (job.segment_id % 8);
  const double amplitude = 0.18 * 32767.0;
  double phase = index * chunk.frames * 2.0 * M_PI * frequency / opts.sample_rate;
  for (int i = 0; i < chunk.frames; ++i) {
    const auto sample = static_cast<int16_t>(std::sin(phase) * amplitude);
    chunk.samples[static_cast<size_t>(i)] = sample;
    phase += 2.0 * M_PI * frequency / opts.sample_rate;
  }
  return chunk;
}

class AudioSink {
 public:
  virtual ~AudioSink() = default;
  virtual void open(const Options& opts) = 0;
  virtual bool write(const PcmChunk& chunk, const Options& opts) = 0;
  virtual void flush() = 0;
  virtual void close() = 0;
};

class NullAudioSink final : public AudioSink {
 public:
  void open(const Options&) override {}

  bool write(const PcmChunk& chunk, const Options& opts) override {
    const auto duration = std::chrono::duration<double>(
        static_cast<double>(chunk.frames) / static_cast<double>(opts.sample_rate));
    std::this_thread::sleep_for(duration);
    return true;
  }

  void flush() override {}
  void close() override {}
};

class WavAudioSink final : public AudioSink {
 public:
  void open(const Options& opts) override {
    path_ = opts.wav_path;
    output_.open(path_, std::ios::binary | std::ios::trunc);
    if (!output_) {
      throw std::runtime_error("Cannot open WAV output: " + path_);
    }
    write_placeholder_header(opts);
  }

  bool write(const PcmChunk& chunk, const Options& opts) override {
    output_.write(reinterpret_cast<const char*>(chunk.samples.data()),
                  static_cast<std::streamsize>(chunk.samples.size() * sizeof(int16_t)));
    data_bytes_ += static_cast<uint32_t>(chunk.samples.size() * sizeof(int16_t));
    output_.flush();
    const auto duration = std::chrono::duration<double>(
        static_cast<double>(chunk.frames) / static_cast<double>(opts.sample_rate));
    std::this_thread::sleep_for(duration);
    return static_cast<bool>(output_);
  }

  void flush() override {
    output_.flush();
  }

  void close() override {
    if (!output_) {
      return;
    }
    output_.seekp(0, std::ios::beg);
    write_header(sample_rate_, channels_, data_bytes_);
    output_.close();
  }

 private:
  void write_placeholder_header(const Options& opts) {
    sample_rate_ = opts.sample_rate;
    channels_ = opts.channels;
    write_header(sample_rate_, channels_, 0);
  }

  void write_u16(uint16_t value) {
    output_.put(static_cast<char>(value & 0xff));
    output_.put(static_cast<char>((value >> 8) & 0xff));
  }

  void write_u32(uint32_t value) {
    output_.put(static_cast<char>(value & 0xff));
    output_.put(static_cast<char>((value >> 8) & 0xff));
    output_.put(static_cast<char>((value >> 16) & 0xff));
    output_.put(static_cast<char>((value >> 24) & 0xff));
  }

  void write_header(int sample_rate, int channels, uint32_t data_bytes) {
    const uint16_t bits_per_sample = 16;
    const uint32_t byte_rate = static_cast<uint32_t>(sample_rate * channels * bits_per_sample / 8);
    const uint16_t block_align = static_cast<uint16_t>(channels * bits_per_sample / 8);
    output_.write("RIFF", 4);
    write_u32(36 + data_bytes);
    output_.write("WAVE", 4);
    output_.write("fmt ", 4);
    write_u32(16);
    write_u16(1);
    write_u16(static_cast<uint16_t>(channels));
    write_u32(static_cast<uint32_t>(sample_rate));
    write_u32(byte_rate);
    write_u16(block_align);
    write_u16(bits_per_sample);
    output_.write("data", 4);
    write_u32(data_bytes);
  }

  std::string path_;
  std::ofstream output_;
  int sample_rate_ = 0;
  int channels_ = 0;
  uint32_t data_bytes_ = 0;
};

#if EDGEVOICE_HAS_ALSA
class AlsaAudioSink final : public AudioSink {
 public:
  void open(const Options& opts) override {
    const int rc = snd_pcm_open(&handle_, opts.alsa_device.c_str(), SND_PCM_STREAM_PLAYBACK, 0);
    if (rc < 0) {
      throw std::runtime_error("snd_pcm_open failed: " + std::string(snd_strerror(rc)));
    }

    snd_pcm_hw_params_t* params = nullptr;
    snd_pcm_hw_params_alloca(&params);
    check(snd_pcm_hw_params_any(handle_, params), "snd_pcm_hw_params_any");
    check(snd_pcm_hw_params_set_access(handle_, params, SND_PCM_ACCESS_RW_INTERLEAVED),
          "snd_pcm_hw_params_set_access");
    check(snd_pcm_hw_params_set_format(handle_, params, SND_PCM_FORMAT_S16_LE),
          "snd_pcm_hw_params_set_format");
    check(snd_pcm_hw_params_set_channels(handle_, params, static_cast<unsigned int>(opts.channels)),
          "snd_pcm_hw_params_set_channels");

    unsigned int rate = static_cast<unsigned int>(opts.sample_rate);
    check(snd_pcm_hw_params_set_rate_near(handle_, params, &rate, nullptr),
          "snd_pcm_hw_params_set_rate_near");

    snd_pcm_uframes_t period_frames =
        static_cast<snd_pcm_uframes_t>(std::max(1, opts.sample_rate * opts.period_ms / 1000));
    snd_pcm_uframes_t buffer_frames =
        static_cast<snd_pcm_uframes_t>(std::max(2, opts.sample_rate * opts.buffer_ms / 1000));
    check(snd_pcm_hw_params_set_period_size_near(handle_, params, &period_frames, nullptr),
          "snd_pcm_hw_params_set_period_size_near");
    check(snd_pcm_hw_params_set_buffer_size_near(handle_, params, &buffer_frames),
          "snd_pcm_hw_params_set_buffer_size_near");
    check(snd_pcm_hw_params(handle_, params), "snd_pcm_hw_params");
    check(snd_pcm_prepare(handle_), "snd_pcm_prepare");
  }

  bool write(const PcmChunk& chunk, const Options& opts) override {
    const int16_t* cursor = chunk.samples.data();
    snd_pcm_sframes_t frames_left = static_cast<snd_pcm_sframes_t>(chunk.frames);
    while (frames_left > 0) {
      const snd_pcm_sframes_t written = snd_pcm_writei(handle_, cursor, frames_left);
      if (written == -EPIPE) {
        snd_pcm_prepare(handle_);
        return false;
      }
      if (written < 0) {
        const int recovered = snd_pcm_recover(handle_, static_cast<int>(written), 1);
        if (recovered < 0) {
          return false;
        }
        continue;
      }
      frames_left -= written;
      cursor += written * opts.channels;
    }
    return true;
  }

  void flush() override {
    if (handle_ != nullptr) {
      snd_pcm_drop(handle_);
      snd_pcm_prepare(handle_);
    }
  }

  void close() override {
    if (handle_ != nullptr) {
      snd_pcm_drain(handle_);
      snd_pcm_close(handle_);
      handle_ = nullptr;
    }
  }

 private:
  static void check(int rc, const char* label) {
    if (rc < 0) {
      throw std::runtime_error(std::string(label) + " failed: " + snd_strerror(rc));
    }
  }

  snd_pcm_t* handle_ = nullptr;
};
#endif

std::unique_ptr<AudioSink> make_audio_sink(const Options& opts) {
  if (opts.audio == "null") {
    return std::make_unique<NullAudioSink>();
  }
  if (opts.audio == "wav") {
    return std::make_unique<WavAudioSink>();
  }
  if (opts.audio == "alsa") {
#if EDGEVOICE_HAS_ALSA
    return std::make_unique<AlsaAudioSink>();
#else
    throw std::runtime_error("This binary was built without ALSA support");
#endif
  }
  throw std::runtime_error("Unsupported audio backend: " + opts.audio);
}

void audio_worker(BlockingQueue<PcmChunk>& jitter_buffer,
                  RunState& state,
                  const Options& opts,
                  Metrics& metrics) {
  auto sink = make_audio_sink(opts);
  sink->open(opts);

  std::deque<PcmChunk> local_prebuffer;
  int buffered_frames = 0;
  bool queue_closed = false;
  bool playback_started = false;

  while (true) {
    if (state.flush_requested.exchange(false)) {
      local_prebuffer.clear();
      buffered_frames = 0;
      jitter_buffer.clear();
      sink->flush();
      metrics.mark_barge_flushed();
      playback_started = false;
    }

    if (!playback_started) {
      while (buffered_frames < opts.jitter_frames()) {
        PcmChunk chunk;
        const auto result = jitter_buffer.pop_for(chunk, std::chrono::milliseconds(10));
        if (result == BlockingQueue<PcmChunk>::PopResult::Item) {
          buffered_frames += chunk.frames;
          local_prebuffer.push_back(std::move(chunk));
        } else if (result == BlockingQueue<PcmChunk>::PopResult::Closed) {
          queue_closed = true;
          break;
        } else if (!local_prebuffer.empty()) {
          break;
        }
      }

      if (local_prebuffer.empty() && queue_closed) {
        break;
      }
      if (!local_prebuffer.empty()) {
        playback_started = true;
      }
    }

    PcmChunk chunk;
    if (!local_prebuffer.empty()) {
      chunk = std::move(local_prebuffer.front());
      buffered_frames -= chunk.frames;
      local_prebuffer.pop_front();
    } else {
      const auto result =
          jitter_buffer.pop_for(chunk, std::chrono::milliseconds(std::max(1, opts.period_ms)));
      if (result == BlockingQueue<PcmChunk>::PopResult::Closed) {
        break;
      }
      if (result == BlockingQueue<PcmChunk>::PopResult::Timeout) {
        metrics.mark_underrun();
        continue;
      }
    }

    if (state.flush_requested.exchange(false)) {
      jitter_buffer.clear();
      sink->flush();
      metrics.mark_barge_flushed();
      playback_started = false;
      continue;
    }

    metrics.mark_playback_start(chunk, opts.sample_rate);
    if (!sink->write(chunk, opts)) {
      metrics.mark_underrun();
    }
  }

  sink->close();
}

void tts_worker(BlockingQueue<TextJob>& text_queue,
                BlockingQueue<PcmChunk>& jitter_buffer,
                RunState& state,
                const Options& opts,
                Metrics& metrics) {
  TextJob job;
  while (text_queue.pop(job)) {
    const int epoch = state.epoch.load();
    std::this_thread::sleep_for(std::chrono::milliseconds(std::max(0, opts.tts_first_chunk_ms)));

    for (int i = 0; i < opts.tts_chunks_per_segment; ++i) {
      if (epoch != state.epoch.load() || job.epoch != state.epoch.load()) {
        break;
      }

      PcmChunk chunk = generate_pcm_chunk(opts, job, i);
      metrics.mark_pcm_chunk();
      if (!jitter_buffer.push(std::move(chunk))) {
        return;
      }
      std::this_thread::sleep_for(
          std::chrono::milliseconds(std::max(0, opts.tts_inter_chunk_gap_ms)));
    }
  }
  jitter_buffer.close();
}

void asr_simulator(BlockingQueue<TextJob>& text_queue,
                   RunState& state,
                   const Options& opts,
                   Metrics& metrics) {
  SentenceSplitter splitter(opts.split_min_tokens, opts.split_max_tokens);
  const auto partials = make_partials(scenario_text(opts), opts.asr_words_per_partial);
  int segment_id = 0;

  for (const auto& partial : partials) {
    std::this_thread::sleep_for(std::chrono::milliseconds(std::max(0, opts.asr_partial_ms)));
    const auto segments = splitter.process_partial(partial);
    for (const auto& text : segments) {
      TextJob job;
      job.segment_id = ++segment_id;
      job.epoch = state.epoch.load();
      job.text = text;
      job.boundary_time = Clock::now();
      metrics.mark_segment(job);
      text_queue.push(std::move(job));
    }
  }

  for (const auto& text : splitter.flush()) {
    TextJob job;
    job.segment_id = ++segment_id;
    job.epoch = state.epoch.load();
    job.text = text;
    job.boundary_time = Clock::now();
    metrics.mark_segment(job);
    text_queue.push(std::move(job));
  }

  text_queue.close();
}

void flush_audio_pipeline(BlockingQueue<TextJob>& text_queue,
                          BlockingQueue<PcmChunk>& jitter_buffer,
                          RunState& state) {
  state.epoch.fetch_add(1);
  text_queue.clear();
  jitter_buffer.clear();
  state.flush_requested.store(true);
}

std::string run_once(const Options& opts, int iteration) {
  BlockingQueue<TextJob> text_queue;
  BlockingQueue<PcmChunk> jitter_buffer;
  RunState state;
  Metrics metrics(iteration);

  std::thread audio([&] { audio_worker(jitter_buffer, state, opts, metrics); });
  std::thread tts([&] { tts_worker(text_queue, jitter_buffer, state, opts, metrics); });
  std::thread asr([&] { asr_simulator(text_queue, state, opts, metrics); });

  std::thread barge;
  if (opts.barge_in_ms > 0) {
    barge = std::thread([&] {
      std::this_thread::sleep_for(std::chrono::milliseconds(opts.barge_in_ms));
      metrics.mark_barge_request();
      flush_audio_pipeline(text_queue, jitter_buffer, state);
    });
  }

  asr.join();
  tts.join();
  audio.join();
  if (barge.joinable()) {
    barge.join();
  }

  return metrics.to_json(opts, "ok");
}

void append_line(const std::string& path, const std::string& line) {
  if (path.empty()) {
    return;
  }
  std::ofstream out(path, std::ios::app);
  if (!out) {
    throw std::runtime_error("Cannot open metrics output: " + path);
  }
  out << line << "\n";
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Options opts = parse_options(argc, argv);
    for (int iteration = 1; iteration <= opts.iterations; ++iteration) {
      const std::string result = run_once(opts, iteration);
      std::cout << result << std::endl;
      append_line(opts.out_path, result);
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "edge_voice_pipeline error: " << error.what() << std::endl;
    return 1;
  }
}
