/**
 * Whistle detection for Booster robot microphone (libduerwen).
 * Pipeline: 6ch ALSA -> Duerwen DSP -> AEC 3ch -> FFT whistle detection.
 * Publishes to /whistle_detected ROS2 topic when whistle is heard.
 */

#include "whistle_detection.h"

extern "C" {
#include <RecvDataCache.h>
#include <WakeupApi.h>
#include <duerwen_alsa.h>
}

#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <array>
#include <cmath>
#include <string>
#include <vector>

#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>

namespace {

constexpr int kDefaultChannels = 6;
constexpr int kDefaultProcessingFrameSamples = 1024;
constexpr int kDefaultSampleRate = 16000;
constexpr int kMicOutputChannels = 3;
constexpr int kRefChannelIndex = 4;
constexpr const char *kDefaultPcmDevice = "hw:1,0";
constexpr const char *kDefaultWhistleTopic = "/whistle_detected";
constexpr const char *kDefaultPublishMessage = "whistle_detected";
constexpr double kPi = 3.14159265358979323846;

volatile sig_atomic_t g_running = 1;

void sigintHandler(int) { g_running = 0; }

struct MonoSpectralConfig {
  bool enable = true;
  double min_rms = 0.055;
  double min_peak_hz = 2300.0;
  double max_peak_hz = 3300.0;
  double min_peak_magnitude = 0.004;
  double min_band_ratio = 0.35;
  int required_blocks = 2;
  int cooldown_blocks = 15;
  bool log_features = false;
};

class MonoSpectralDetector {
public:
  MonoSpectralDetector(int frame_samples, int sample_rate,
                       const MonoSpectralConfig &config)
      : frame_samples_(frame_samples), sample_rate_(sample_rate),
        config_(config), real_buffer_(frame_samples),
        complex_buffer_(frame_samples / 2 + 1) {
    plan_ = fftwf_plan_dft_r2c_1d(
        frame_samples_, real_buffer_.data(),
        reinterpret_cast<fftwf_complex *>(complex_buffer_.data()),
        FFTW_ESTIMATE);
  }

  ~MonoSpectralDetector() { fftwf_destroy_plan(plan_); }

  bool process(const int16_t *interleaved_3ch) {
    if (!config_.enable || !interleaved_3ch)
      return false;
    if (cooldown_blocks_ > 0) {
      --cooldown_blocks_;
      return false;
    }

    double sum_sq = 0.0;
    double sum = 0.0;
    for (int i = 0; i < frame_samples_; ++i) {
      const double sample = interleaved_3ch[i * kMicOutputChannels] / 32768.0;
      sum += sample;
      sum_sq += sample * sample;
      real_buffer_[i] = static_cast<float>(sample);
    }
    const double mean = sum / frame_samples_;
    const double rms = std::sqrt(sum_sq / frame_samples_);
    for (int i = 0; i < frame_samples_; ++i) {
      const double phase = 2.0 * kPi * i / (frame_samples_ - 1);
      const double window = 0.5 - 0.5 * std::cos(phase);
      real_buffer_[i] = static_cast<float>((real_buffer_[i] - mean) * window);
    }

    fftwf_execute(plan_);

    const double bin_hz = static_cast<double>(sample_rate_) / frame_samples_;
    double band_sum = 0.0;
    double full_sum = 0.0;
    double peak_magnitude = 0.0;
    double peak_hz = 0.0;
    for (int i = 1; i <= frame_samples_ / 2; ++i) {
      const double hz = i * bin_hz;
      const auto &c = complex_buffer_[i];
      const double magnitude = std::hypot(c[0], c[1]) / frame_samples_;
      if (hz >= 300.0 && hz <= 7800.0) {
        full_sum += magnitude;
      }
      if (hz >= config_.min_peak_hz && hz <= config_.max_peak_hz) {
        band_sum += magnitude;
        if (magnitude > peak_magnitude) {
          peak_magnitude = magnitude;
          peak_hz = hz;
        }
      }
    }

    const double band_ratio = full_sum > 1e-9 ? band_sum / full_sum : 0.0;
    const bool block_match =
        rms >= config_.min_rms &&
        peak_magnitude >= config_.min_peak_magnitude &&
        band_ratio >= config_.min_band_ratio;
    consecutive_blocks_ = block_match ? consecutive_blocks_ + 1 : 0;

    if (config_.log_features) {
      std::printf("mono: rms=%0.4f peak_hz=%0.0f peak=%0.4f band=%0.3f "
                  "blocks=%d\n",
                  rms, peak_hz, peak_magnitude, band_ratio,
                  consecutive_blocks_);
    }

    if (consecutive_blocks_ >= config_.required_blocks) {
      reset();
      return true;
    }
    return false;
  }

  void reset() {
    consecutive_blocks_ = 0;
    cooldown_blocks_ = std::max(0, config_.cooldown_blocks);
  }

private:
  int frame_samples_;
  int sample_rate_;
  MonoSpectralConfig config_;
  std::vector<float> real_buffer_;
  std::vector<std::array<float, 2>> complex_buffer_;
  fftwf_plan plan_ = nullptr;
  int consecutive_blocks_ = 0;
  int cooldown_blocks_ = 0;
};

#pragma pack(push, 1)
struct WavHeader {
  char chunk_id[4];
  uint32_t chunk_size;
  char format[4];
  char sub_chunk1_id[4];
  uint32_t sub_chunk1_size;
  uint16_t audio_format;
  uint16_t num_channels;
  uint32_t sample_rate;
  uint32_t byte_rate;
  uint16_t block_align;
  uint16_t bits_per_sample;
  char sub_chunk2_id[4];
  uint32_t sub_chunk2_size;
};
#pragma pack(pop)

void writeWavHeader(FILE *file, int channels, int sample_rate,
                    int bits_per_sample) {
  WavHeader h = {};
  std::memcpy(h.chunk_id, "RIFF", 4);
  h.chunk_size = 0;
  std::memcpy(h.format, "WAVE", 4);
  std::memcpy(h.sub_chunk1_id, "fmt ", 4);
  h.sub_chunk1_size = 16;
  h.audio_format = 1;
  h.num_channels = static_cast<uint16_t>(channels);
  h.sample_rate = static_cast<uint32_t>(sample_rate);
  h.bits_per_sample = static_cast<uint16_t>(bits_per_sample);
  h.byte_rate = sample_rate * channels * bits_per_sample / 8;
  h.block_align = channels * bits_per_sample / 8;
  std::memcpy(h.sub_chunk2_id, "data", 4);
  h.sub_chunk2_size = 0;
  std::fwrite(&h, sizeof(WavHeader), 1, file);
}

void finalizeWavHeader(FILE *file) {
  if (!file) return;
  uint32_t file_size = static_cast<uint32_t>(std::ftell(file));
  uint32_t chunk_size = file_size - 8;
  uint32_t data_size = file_size - sizeof(WavHeader);
  std::fseek(file, 4, SEEK_SET);
  std::fwrite(&chunk_size, 4, 1, file);
  std::fseek(file, 40, SEEK_SET);
  std::fwrite(&data_size, 4, 1, file);
}

void printUsage(const char *prog) {
  std::fprintf(stderr, "Usage: %s [-r|--record <output.wav>]\n", prog);
  std::fprintf(stderr, "  -r, --record   Record 3ch RAW output to a WAV file.\n");
}

} // namespace

int main(int argc, char **argv) {
  rclcpp::init(argc, argv);
  auto node = rclcpp::Node::make_shared("whistle_detection");

  const char *record_path = nullptr;
  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "-r") == 0 || std::strcmp(argv[i], "--record") == 0) {
      if (i + 1 >= argc) {
        printUsage(argv[0]);
        rclcpp::shutdown();
        return 1;
      }
      record_path = argv[++i];
    } else if (std::strcmp(argv[i], "-h") == 0 || std::strcmp(argv[i], "--help") == 0) {
      printUsage(argv[0]);
      rclcpp::shutdown();
      return 0;
    }
  }

  const auto pcm_device = node->declare_parameter<std::string>(
      "audio.pcm_device", kDefaultPcmDevice);
  const int channels =
      node->declare_parameter<int>("audio.channels", kDefaultChannels);
  const int sample_rate =
      node->declare_parameter<int>("audio.sample_rate", kDefaultSampleRate);
  const int processing_frame_samples = node->declare_parameter<int>(
      "audio.processing_frame_samples", kDefaultProcessingFrameSamples);
  const bool use_duerwen_aec =
      node->declare_parameter<bool>("audio.use_duerwen_aec", true);
  const auto whistle_topic = node->declare_parameter<std::string>(
      "detection.topic", kDefaultWhistleTopic);
  const auto publish_message = node->declare_parameter<std::string>(
      "detection.publish_message", kDefaultPublishMessage);

  whistle::DetectorConfig detector_config;
  detector_config.threshold = static_cast<float>(
      node->declare_parameter<double>("detection.threshold", 0.995));
  detector_config.score_bias = static_cast<float>(
      node->declare_parameter<double>("detection.score_bias", 0.6050399));
  detector_config.noise_scale = static_cast<float>(
      node->declare_parameter<double>("detection.noise_scale", 10.0));
  detector_config.log_scores =
      node->declare_parameter<bool>("detection.log_scores", false);

  MonoSpectralConfig mono_config;
  mono_config.enable =
      node->declare_parameter<bool>("detection.mono_spectral.enable", true);
  mono_config.min_rms =
      node->declare_parameter<double>("detection.mono_spectral.min_rms", 0.055);
  mono_config.min_peak_hz = node->declare_parameter<double>(
      "detection.mono_spectral.min_peak_hz", 2300.0);
  mono_config.max_peak_hz = node->declare_parameter<double>(
      "detection.mono_spectral.max_peak_hz", 3300.0);
  mono_config.min_peak_magnitude = node->declare_parameter<double>(
      "detection.mono_spectral.min_peak_magnitude", 0.004);
  mono_config.min_band_ratio = node->declare_parameter<double>(
      "detection.mono_spectral.min_band_ratio", 0.35);
  mono_config.required_blocks = node->declare_parameter<int>(
      "detection.mono_spectral.required_blocks", 2);
  mono_config.cooldown_blocks = node->declare_parameter<int>(
      "detection.mono_spectral.cooldown_blocks", 15);
  mono_config.log_features = node->declare_parameter<bool>(
      "detection.mono_spectral.log_features", false);

  if (channels <= 0) {
    RCLCPP_ERROR(node->get_logger(), "audio.channels must be positive, got %d",
                 channels);
    rclcpp::shutdown();
    return 1;
  }
  if (use_duerwen_aec &&
      (channels <= kRefChannelIndex || channels < kMicOutputChannels)) {
    RCLCPP_ERROR(node->get_logger(),
                 "audio.channels must be at least %d when audio.use_duerwen_aec "
                 "is true, got %d",
                 kRefChannelIndex + 1, channels);
    rclcpp::shutdown();
    return 1;
  }
  if (sample_rate <= 0) {
    RCLCPP_ERROR(node->get_logger(), "audio.sample_rate must be positive, got %d",
                 sample_rate);
    rclcpp::shutdown();
    return 1;
  }
  if (processing_frame_samples <
      static_cast<int>(whistle::WhistleDetector::kFftFrameSize)) {
    RCLCPP_ERROR(node->get_logger(),
                 "audio.processing_frame_samples must be at least %u, got %d",
                 whistle::WhistleDetector::kFftFrameSize,
                 processing_frame_samples);
    rclcpp::shutdown();
    return 1;
  }
  if (detector_config.threshold <= 0.f || detector_config.threshold >= 1.f) {
    RCLCPP_ERROR(node->get_logger(),
                 "detection.threshold must be in (0, 1), got %.6f",
                 detector_config.threshold);
    rclcpp::shutdown();
    return 1;
  }
  if (mono_config.min_rms < 0.0 || mono_config.min_peak_magnitude < 0.0 ||
      mono_config.min_band_ratio < 0.0 ||
      mono_config.min_peak_hz >= mono_config.max_peak_hz ||
      mono_config.required_blocks <= 0 || mono_config.cooldown_blocks < 0) {
    RCLCPP_ERROR(node->get_logger(),
                 "Invalid detection.mono_spectral parameters");
    rclcpp::shutdown();
    return 1;
  }

  auto publisher =
      node->create_publisher<std_msgs::msg::String>(whistle_topic, 10);

  std::signal(SIGINT, sigintHandler);

  std::vector<unsigned char> cache_buf(1024 * 64, 0);
  RecvDataCacheInfo alsa_cache;
  RecvDataCacheInit(&alsa_cache, cache_buf.data(), static_cast<unsigned int>(cache_buf.size()));

  HWWakeup wakeup_handle = nullptr;
  if (use_duerwen_aec) {
    int ret = Duerwen_wakeup_init(&wakeup_handle, 0);
    if (ret != 0) {
      std::fprintf(stderr, "Duerwen_wakeup_init failed: %d\n", ret);
      rclcpp::shutdown();
      return 1;
    }
  }

  void *alsa_handle = nullptr;
  int ret = duerwen_alsa_init(&alsa_handle, const_cast<char *>(pcm_device.c_str()),
                              channels, sample_rate, SND_PCM_STREAM_CAPTURE);
  if (ret != 0) {
    std::fprintf(stderr, "duerwen_alsa_init failed: %d\n", ret);
    if (wakeup_handle)
      Duerwen_wakeup_unit(wakeup_handle);
    rclcpp::shutdown();
    return 1;
  }

  const auto *alsa_params = static_cast<const DuerWenAlsaParams *>(alsa_handle);
  const int alsa_period_frames =
      alsa_params && alsa_params->frames > 0
          ? static_cast<int>(alsa_params->frames)
          : processing_frame_samples;

  std::vector<int16_t> sources(alsa_period_frames * channels);
  std::vector<int16_t> source_accumulator(processing_frame_samples * channels);
  int accumulated_frames = 0;
  std::vector<int16_t> mic1(processing_frame_samples),
      mic2(processing_frame_samples), mic3(processing_frame_samples);
  std::vector<int16_t> ref1(processing_frame_samples);
  std::vector<int16_t> aec1(processing_frame_samples),
      aec2(processing_frame_samples), aec3(processing_frame_samples);
  std::vector<int16_t> raw_interleaved(processing_frame_samples *
                                       kMicOutputChannels);
  std::vector<int16_t> naec(processing_frame_samples);

  FILE *record_file = nullptr;
  if (record_path) {
    record_file = std::fopen(record_path, "wb");
    if (!record_file) {
      std::fprintf(stderr, "Cannot open record file: %s\n", record_path);
      duerwen_alsa_unit(alsa_handle);
      if (wakeup_handle)
        Duerwen_wakeup_unit(wakeup_handle);
      rclcpp::shutdown();
      return 1;
    }
    writeWavHeader(record_file, kMicOutputChannels, sample_rate, 16);
    RCLCPP_INFO(node->get_logger(), "Recording 3ch RAW to %s", record_path);
  }

  whistle::WhistleDetector detector(detector_config);
  MonoSpectralDetector mono_detector(processing_frame_samples, sample_rate,
                                     mono_config);
  bool was_ready = false;

  RCLCPP_INFO(node->get_logger(),
              "Whistle detection started on topic '%s'", whistle_topic.c_str());
  RCLCPP_INFO(node->get_logger(),
              "Audio config: device=%s channels=%d sample_rate=%d "
              "alsa_period_frames=%d processing_frame_samples=%d "
              "use_duerwen_aec=%s",
              pcm_device.c_str(), channels, sample_rate, alsa_period_frames,
              processing_frame_samples, use_duerwen_aec ? "true" : "false");
  RCLCPP_INFO(node->get_logger(),
              "Detection config: threshold=%.6f score_bias=%.6f "
              "noise_scale=%.3f log_scores=%s",
              detector_config.threshold, detector_config.score_bias,
              detector_config.noise_scale,
              detector_config.log_scores ? "true" : "false");
  RCLCPP_INFO(node->get_logger(),
              "Mono spectral config: enable=%s min_rms=%.4f "
              "peak_hz=%.0f-%.0f min_peak=%.4f min_band=%.3f "
              "required_blocks=%d cooldown_blocks=%d log_features=%s",
              mono_config.enable ? "true" : "false", mono_config.min_rms,
              mono_config.min_peak_hz, mono_config.max_peak_hz,
              mono_config.min_peak_magnitude, mono_config.min_band_ratio,
              mono_config.required_blocks, mono_config.cooldown_blocks,
              mono_config.log_features ? "true" : "false");
  RCLCPP_INFO(node->get_logger(),
              "Whistle detection calibrating (need ~10s of ambient noise)...");

  auto processCapturedBlock = [&]() {
    if (use_duerwen_aec) {
      for (int i = 0; i < processing_frame_samples; ++i) {
        mic1[i] = source_accumulator[i * channels + 0];
        mic2[i] = source_accumulator[i * channels + 1];
        mic3[i] = source_accumulator[i * channels + 2];
        ref1[i] = source_accumulator[i * channels + kRefChannelIndex];
      }

      const int dsp_ret = Duerwen_wakeup_three_write_data(
          wakeup_handle, mic1.data(), mic2.data(), mic3.data(), ref1.data(),
          aec1.data(), aec2.data(), aec3.data(), naec.data());
      if (dsp_ret != 0) {
        RCLCPP_WARN_THROTTLE(node->get_logger(), *node->get_clock(), 5000,
                             "Duerwen_wakeup_three_write_data returned %d",
                             dsp_ret);
      }

      for (int i = 0; i < processing_frame_samples; ++i) {
        raw_interleaved[i * kMicOutputChannels + 0] = aec1[i];
        raw_interleaved[i * kMicOutputChannels + 1] = aec2[i];
        raw_interleaved[i * kMicOutputChannels + 2] = aec3[i];
      }
    } else {
      for (int i = 0; i < processing_frame_samples; ++i) {
        const int16_t sample = source_accumulator[i * channels];
        raw_interleaved[i * kMicOutputChannels + 0] = sample;
        raw_interleaved[i * kMicOutputChannels + 1] = sample;
        raw_interleaved[i * kMicOutputChannels + 2] = sample;
      }
    }

    if (record_file) {
      std::fwrite(raw_interleaved.data(), sizeof(int16_t),
                  static_cast<size_t>(processing_frame_samples *
                                      kMicOutputChannels),
                  record_file);
    }

    bool ready =
        detector.processFrame(raw_interleaved.data(), processing_frame_samples);
    const bool mono_detected =
        !use_duerwen_aec && mono_detector.process(raw_interleaved.data());
    if (ready && !was_ready) {
      RCLCPP_INFO(node->get_logger(),
                  "Whistle detection ready (noise floor calibrated)");
      was_ready = true;
    }

    if (detector.whistleDetected() || mono_detected) {
      RCLCPP_INFO(node->get_logger(), "Whistle DETECTED! Publishing to '%s'",
                  whistle_topic.c_str());
      std_msgs::msg::String msg;
      msg.data = publish_message;
      publisher->publish(msg);
      if (detector.whistleDetected()) {
        detector.reset();
        RCLCPP_INFO(node->get_logger(), "Whistle detection recalibrating...");
        was_ready = false;
      }
      mono_detector.reset();
    }
  };

  while (g_running && rclcpp::ok()) {
    rclcpp::spin_some(node);

    int frames = duerwen_alsa_read(alsa_handle, sources.data());
    if (frames <= 0) {
      continue;
    }

    int copied_frames = 0;
    while (copied_frames < frames) {
      const int frames_to_copy =
          std::min(processing_frame_samples - accumulated_frames,
                   frames - copied_frames);
      std::copy_n(sources.data() + copied_frames * channels,
                  frames_to_copy * channels,
                  source_accumulator.data() + accumulated_frames * channels);
      copied_frames += frames_to_copy;
      accumulated_frames += frames_to_copy;

      if (accumulated_frames == processing_frame_samples) {
        processCapturedBlock();
        accumulated_frames = 0;
      }
    }
  }

  if (record_file) {
    finalizeWavHeader(record_file);
    std::fclose(record_file);
  }

  if (wakeup_handle)
    Duerwen_wakeup_unit(wakeup_handle);
  duerwen_alsa_unit(alsa_handle);

  rclcpp::shutdown();
  return 0;
}
