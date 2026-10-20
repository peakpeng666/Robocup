#include "fftw_allocator.h"

extern "C" {
#include <RecvDataCache.h>
#include <duerwen_alsa.h>
}

#include <algorithm>
#include <array>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <fftw3.h>
#include <yaml-cpp/yaml.h>

namespace {

constexpr int kDefaultChannels = 1;
constexpr int kDefaultProcessingFrameSamples = 1024;
constexpr int kDefaultSampleRate = 16000;
constexpr const char *kDefaultPcmDevice = "hw:3,0";
constexpr double kPi = 3.14159265358979323846;

volatile sig_atomic_t g_running = 1;

void sigintHandler(int) { g_running = 0; }

struct Options {
  std::string config_path;
  double noise_seconds = 10.0;
  double whistle_seconds = 8.0;
  double scan_min_hz = 1500.0;
  double scan_max_hz = 5000.0;
  bool no_prompt = false;
  bool assume_yes = false;
  bool no_overwrite = false;
  bool help = false;
};

struct SpectralFeature {
  double rms = 0.0;
  double peak_hz = 0.0;
  double peak_magnitude = 0.0;
  double full_sum = 0.0;
  std::vector<float> magnitudes;
};

struct PhaseStats {
  double rms_p50 = 0.0;
  double rms_p90 = 0.0;
  double rms_p99 = 0.0;
  double peak_p50 = 0.0;
  double peak_p90 = 0.0;
  double peak_p99 = 0.0;
  double band_p50 = 0.0;
  double band_p90 = 0.0;
  double band_p99 = 0.0;
};

struct RecommendedConfig {
  double min_rms = 0.0;
  double min_peak_hz = 0.0;
  double max_peak_hz = 0.0;
  double min_peak_magnitude = 0.0;
  double min_band_ratio = 0.0;
  int required_blocks = 3;
  int cooldown_blocks = 20;
};

void printUsage(const char *prog) {
  std::cout << "Usage: " << prog
            << " <config.yaml> [--noise-sec N] [--whistle-sec N]"
               " [--scan-min-hz HZ] [--scan-max-hz HZ]"
               " [--no-prompt] [--yes] [--no-overwrite]\n\n"
            << "Example:\n"
            << "  ros2 run whistle_detection whistle_calibrate "
               "src/whistle_detection/config/config_local.yaml\n";
}

bool parseDoubleArg(int argc, char **argv, int &i, double *value) {
  if (i + 1 >= argc) {
    return false;
  }
  char *end = nullptr;
  const double parsed = std::strtod(argv[++i], &end);
  if (!end || *end != '\0' || !std::isfinite(parsed)) {
    return false;
  }
  *value = parsed;
  return true;
}

bool parseOptions(int argc, char **argv, Options *options) {
  for (int i = 1; i < argc; ++i) {
    const std::string arg(argv[i]);
    if (arg == "-h" || arg == "--help") {
      printUsage(argv[0]);
      options->help = true;
      return true;
    }
    if (arg == "--ros-args") {
      break;
    }
    if (arg == "--noise-sec") {
      if (!parseDoubleArg(argc, argv, i, &options->noise_seconds))
        return false;
    } else if (arg == "--whistle-sec") {
      if (!parseDoubleArg(argc, argv, i, &options->whistle_seconds))
        return false;
    } else if (arg == "--scan-min-hz") {
      if (!parseDoubleArg(argc, argv, i, &options->scan_min_hz))
        return false;
    } else if (arg == "--scan-max-hz") {
      if (!parseDoubleArg(argc, argv, i, &options->scan_max_hz))
        return false;
    } else if (arg == "--no-prompt") {
      options->no_prompt = true;
    } else if (arg == "--yes" || arg == "-y") {
      options->assume_yes = true;
    } else if (arg == "--no-overwrite") {
      options->no_overwrite = true;
    } else if (!arg.empty() && arg[0] != '-' && options->config_path.empty()) {
      options->config_path = arg;
    } else {
      return false;
    }
  }

  if (options->config_path.empty() || options->noise_seconds <= 0.0 ||
      options->whistle_seconds <= 0.0 ||
      options->scan_min_hz <= 0.0 ||
      options->scan_min_hz >= options->scan_max_hz) {
    return false;
  }
  return true;
}

double percentile(std::vector<double> values, double q) {
  if (values.empty())
    return 0.0;
  std::sort(values.begin(), values.end());
  const double clamped_q = std::clamp(q, 0.0, 1.0);
  const double pos = clamped_q * static_cast<double>(values.size() - 1);
  const size_t lo = static_cast<size_t>(std::floor(pos));
  const size_t hi = static_cast<size_t>(std::ceil(pos));
  if (lo == hi)
    return values[lo];
  const double t = pos - static_cast<double>(lo);
  return values[lo] * (1.0 - t) + values[hi] * t;
}

double roundDown(double value, double step) {
  return std::floor(value / step) * step;
}

double roundUp(double value, double step) {
  return std::ceil(value / step) * step;
}

std::string formatDouble(double value, int precision) {
  std::ostringstream oss;
  oss << std::fixed << std::setprecision(precision) << value;
  return oss.str();
}

std::string trim(const std::string &text) {
  const auto begin = text.find_first_not_of(" \t\r\n");
  if (begin == std::string::npos)
    return "";
  const auto end = text.find_last_not_of(" \t\r\n");
  return text.substr(begin, end - begin + 1);
}

bool isIntegerScalar(const std::string &value) {
  const std::string trimmed = trim(value);
  if (trimmed.empty())
    return false;

  size_t i = 0;
  if (trimmed[i] == '-' || trimmed[i] == '+') {
    ++i;
  }
  if (i >= trimmed.size())
    return false;
  for (; i < trimmed.size(); ++i) {
    if (!std::isdigit(static_cast<unsigned char>(trimmed[i])))
      return false;
  }
  return true;
}

bool shouldForceFloatKey(const std::string &key) {
  static const std::vector<std::string> keys = {
      "min_rms",
      "min_peak_hz",
      "max_peak_hz",
      "min_peak_magnitude",
      "min_band_ratio",
      "noise_seconds",
      "whistle_seconds",
      "noise_p99_rms",
      "noise_p99_peak",
      "noise_p99_band_ratio",
      "whistle_p10_rms",
      "whistle_p10_peak",
      "whistle_p10_band_ratio",
      "whistle_peak_hz_p50",
  };
  return std::find(keys.begin(), keys.end(), key) != keys.end();
}

std::string forceYamlFloatScalars(const std::string &yaml) {
  std::istringstream in(yaml);
  std::ostringstream out;
  std::string line;
  while (std::getline(in, line)) {
    const auto colon = line.find(':');
    if (colon != std::string::npos) {
      const std::string key = trim(line.substr(0, colon));
      const std::string value = trim(line.substr(colon + 1));
      if (shouldForceFloatKey(key) && isIntegerScalar(value)) {
        line += ".0";
      }
    }
    out << line << "\n";
  }
  return out.str();
}

std::string currentTimestamp() {
  std::time_t now = std::time(nullptr);
  std::tm tm{};
  localtime_r(&now, &tm);

  char buffer[32] = {};
  std::strftime(buffer, sizeof(buffer), "%Y%m%d_%H%M%S", &tm);
  return buffer;
}

YAML::Node paramsRootForRead(const YAML::Node &config) {
  if (config["whistle_detection"] &&
      config["whistle_detection"]["ros__parameters"]) {
    return config["whistle_detection"]["ros__parameters"];
  }
  return config;
}

YAML::Node paramsRootForWrite(YAML::Node &config) {
  if (config["whistle_detection"] &&
      config["whistle_detection"]["ros__parameters"]) {
    return config["whistle_detection"]["ros__parameters"];
  }
  if (config["audio"] || config["detection"]) {
    return config;
  }
  return config["whistle_detection"]["ros__parameters"];
}

template <typename T>
T yamlAsOr(const YAML::Node &node, const char *key, const T &fallback) {
  if (node && node[key]) {
    return node[key].as<T>();
  }
  return fallback;
}

bool writeYamlFile(const std::string &path, const YAML::Node &node) {
  std::ofstream out(path);
  if (!out)
    return false;
  std::ostringstream serialized;
  serialized << node;
  out << forceYamlFloatScalars(serialized.str());
  return true;
}

bool askYesNo(const std::string &question) {
  std::cout << question << " y/n" << std::endl;
  char key = 0;
  std::cin >> key;
  return key == 'y' || key == 'Y';
}

class FeatureExtractor {
public:
  FeatureExtractor(int frame_samples, int sample_rate, double scan_min_hz,
                   double scan_max_hz)
      : frame_samples_(frame_samples), sample_rate_(sample_rate),
        scan_min_hz_(scan_min_hz), scan_max_hz_(scan_max_hz),
        real_buffer_(frame_samples),
        complex_buffer_(frame_samples / 2 + 1) {
    plan_ = fftwf_plan_dft_r2c_1d(
        frame_samples_, real_buffer_.data(),
        reinterpret_cast<fftwf_complex *>(complex_buffer_.data()),
        FFTW_ESTIMATE);
  }

  ~FeatureExtractor() { fftwf_destroy_plan(plan_); }

  SpectralFeature analyze(const int16_t *interleaved, int channels) {
    SpectralFeature feature;
    feature.magnitudes.resize(frame_samples_ / 2 + 1, 0.0f);

    double sum = 0.0;
    double sum_sq = 0.0;
    for (int i = 0; i < frame_samples_; ++i) {
      const double sample = interleaved[i * channels] / 32768.0;
      sum += sample;
      sum_sq += sample * sample;
      real_buffer_[i] = static_cast<float>(sample);
    }

    const double mean = sum / frame_samples_;
    feature.rms = std::sqrt(sum_sq / frame_samples_);
    for (int i = 0; i < frame_samples_; ++i) {
      const double phase = 2.0 * kPi * i / (frame_samples_ - 1);
      const double window = 0.5 - 0.5 * std::cos(phase);
      real_buffer_[i] = static_cast<float>((real_buffer_[i] - mean) * window);
    }

    fftwf_execute(plan_);

    const double bin_hz = static_cast<double>(sample_rate_) / frame_samples_;
    for (int i = 1; i <= frame_samples_ / 2; ++i) {
      const double hz = i * bin_hz;
      const auto &c = complex_buffer_[i];
      const double magnitude = std::hypot(c[0], c[1]) / frame_samples_;
      feature.magnitudes[i] = static_cast<float>(magnitude);

      if (hz >= 300.0 && hz <= 7800.0) {
        feature.full_sum += magnitude;
      }
      if (hz >= scan_min_hz_ && hz <= scan_max_hz_ &&
          magnitude > feature.peak_magnitude) {
        feature.peak_magnitude = magnitude;
        feature.peak_hz = hz;
      }
    }
    return feature;
  }

private:
  int frame_samples_;
  int sample_rate_;
  double scan_min_hz_;
  double scan_max_hz_;
  whistle::fftwf_vector<float> real_buffer_;
  whistle::fftwf_vector<std::array<float, 2>> complex_buffer_;
  fftwf_plan plan_ = nullptr;
};

double bandRatio(const SpectralFeature &feature, int frame_samples,
                 int sample_rate, double min_hz, double max_hz) {
  if (feature.full_sum <= 1e-12)
    return 0.0;
  const double bin_hz = static_cast<double>(sample_rate) / frame_samples;
  double band_sum = 0.0;
  for (size_t i = 1; i < feature.magnitudes.size(); ++i) {
    const double hz = static_cast<double>(i) * bin_hz;
    if (hz >= min_hz && hz <= max_hz) {
      band_sum += feature.magnitudes[i];
    }
  }
  return band_sum / feature.full_sum;
}

std::vector<SpectralFeature>
capturePhase(void *alsa_handle, int channels, int alsa_period_frames, int sample_rate,
             int processing_frame_samples, double seconds,
             FeatureExtractor *extractor, const std::string &label) {
  const int target_blocks = std::max(
      1, static_cast<int>(std::ceil(seconds * sample_rate /
                                    processing_frame_samples)));
  std::vector<int16_t> sources(alsa_period_frames * channels);
  std::vector<int16_t> accumulator(processing_frame_samples * channels);
  int accumulated_frames = 0;
  std::vector<SpectralFeature> features;
  features.reserve(target_blocks);

  int last_percent = -1;
  while (g_running &&
         static_cast<int>(features.size()) < target_blocks) {
    const int frames = duerwen_alsa_read(alsa_handle, sources.data());
    if (frames <= 0)
      continue;

    int copied_frames = 0;
    while (copied_frames < frames &&
           static_cast<int>(features.size()) < target_blocks) {
      const int frames_to_copy =
          std::min(processing_frame_samples - accumulated_frames,
                   frames - copied_frames);
      std::copy_n(sources.data() + copied_frames * channels,
                  frames_to_copy * channels,
                  accumulator.data() + accumulated_frames * channels);
      copied_frames += frames_to_copy;
      accumulated_frames += frames_to_copy;

      if (accumulated_frames == processing_frame_samples) {
        features.push_back(extractor->analyze(accumulator.data(), channels));
        accumulated_frames = 0;

        const int percent = static_cast<int>(
            100.0 * static_cast<double>(features.size()) / target_blocks);
        if (percent / 10 != last_percent / 10) {
          std::cout << label << " capture: " << percent << "%\n";
          last_percent = percent;
        }
      }
    }
  }

  return features;
}

PhaseStats computeStats(const std::vector<SpectralFeature> &features,
                        int frame_samples, int sample_rate, double min_hz,
                        double max_hz) {
  std::vector<double> rms_values;
  std::vector<double> peak_values;
  std::vector<double> band_values;
  rms_values.reserve(features.size());
  peak_values.reserve(features.size());
  band_values.reserve(features.size());

  for (const auto &feature : features) {
    rms_values.push_back(feature.rms);
    peak_values.push_back(feature.peak_magnitude);
    band_values.push_back(
        bandRatio(feature, frame_samples, sample_rate, min_hz, max_hz));
  }

  PhaseStats stats;
  stats.rms_p50 = percentile(rms_values, 0.50);
  stats.rms_p90 = percentile(rms_values, 0.90);
  stats.rms_p99 = percentile(rms_values, 0.99);
  stats.peak_p50 = percentile(peak_values, 0.50);
  stats.peak_p90 = percentile(peak_values, 0.90);
  stats.peak_p99 = percentile(peak_values, 0.99);
  stats.band_p50 = percentile(band_values, 0.50);
  stats.band_p90 = percentile(band_values, 0.90);
  stats.band_p99 = percentile(band_values, 0.99);
  return stats;
}

std::vector<const SpectralFeature *>
selectWhistleCandidates(const std::vector<SpectralFeature> &whistle_features,
                        const PhaseStats &noise_scan_stats) {
  std::vector<const SpectralFeature *> sorted;
  sorted.reserve(whistle_features.size());
  for (const auto &feature : whistle_features) {
    sorted.push_back(&feature);
  }
  std::sort(sorted.begin(), sorted.end(),
            [](const SpectralFeature *a, const SpectralFeature *b) {
              return a->peak_magnitude > b->peak_magnitude;
            });

  const double threshold =
      std::max(noise_scan_stats.peak_p99 * 1.20,
               noise_scan_stats.peak_p90 * 2.00);
  std::vector<const SpectralFeature *> candidates;
  for (const auto *feature : sorted) {
    if (feature->peak_magnitude >= threshold) {
      candidates.push_back(feature);
    }
  }

  const size_t minimum_candidates =
      std::min<size_t>(6, std::max<size_t>(1, sorted.size()));
  if (candidates.size() < minimum_candidates) {
    const size_t fallback_count =
        std::min(sorted.size(), std::max<size_t>(minimum_candidates,
                                                sorted.size() / 5));
    candidates.assign(sorted.begin(), sorted.begin() + fallback_count);
  }

  return candidates;
}

double chooseThreshold(double noise_p99, double signal_p10,
                       double absolute_floor, double signal_factor,
                       double noise_factor) {
  if (signal_p10 > noise_p99) {
    return std::max(absolute_floor,
                    noise_p99 + 0.50 * (signal_p10 - noise_p99));
  }
  return std::max({absolute_floor, signal_p10 * signal_factor,
                   noise_p99 * noise_factor});
}

std::string yamlSnippet(const RecommendedConfig &config) {
  std::ostringstream oss;
  oss << "mono_spectral:\n"
      << "  enable: true\n"
      << "  min_rms: " << formatDouble(config.min_rms, 4) << "\n"
      << "  min_peak_hz: " << formatDouble(config.min_peak_hz, 1) << "\n"
      << "  max_peak_hz: " << formatDouble(config.max_peak_hz, 1) << "\n"
      << "  min_peak_magnitude: "
      << formatDouble(config.min_peak_magnitude, 6) << "\n"
      << "  min_band_ratio: " << formatDouble(config.min_band_ratio, 3)
      << "\n"
      << "  required_blocks: " << config.required_blocks << "\n"
      << "  cooldown_blocks: " << config.cooldown_blocks << "\n"
      << "  log_features: false\n";
  return oss.str();
}

} // namespace

int main(int argc, char **argv) {
  Options options;
  if (!parseOptions(argc, argv, &options)) {
    printUsage(argv[0]);
    return 1;
  }
  if (options.help) {
    return 0;
  }
  if (!std::filesystem::exists(options.config_path)) {
    std::cerr << "Config file not found: " << options.config_path << "\n";
    return 1;
  }

  std::signal(SIGINT, sigintHandler);

  YAML::Node input_config;
  try {
    input_config = YAML::LoadFile(options.config_path);
  } catch (const std::exception &e) {
    std::cerr << "Failed to load " << options.config_path << ": " << e.what()
              << "\n";
    return 1;
  }

  const YAML::Node params = paramsRootForRead(input_config);
  const YAML::Node audio = params["audio"];
  const auto pcm_device =
      yamlAsOr<std::string>(audio, "pcm_device", kDefaultPcmDevice);
  const int channels = yamlAsOr<int>(audio, "channels", kDefaultChannels);
  const int sample_rate =
      yamlAsOr<int>(audio, "sample_rate", kDefaultSampleRate);
  const int processing_frame_samples = yamlAsOr<int>(
      audio, "processing_frame_samples", kDefaultProcessingFrameSamples);
  const bool use_duerwen_aec =
      yamlAsOr<bool>(audio, "use_duerwen_aec", false);

  if (use_duerwen_aec) {
    std::cerr << "whistle_calibrate currently supports the mono USB mic path "
                 "only. Set audio.use_duerwen_aec=false.\n";
    return 1;
  }
  if (channels <= 0 || sample_rate <= 0 || processing_frame_samples <= 0) {
    std::cerr << "Invalid audio parameters in " << options.config_path << "\n";
    return 1;
  }
  if (options.scan_max_hz >= sample_rate / 2.0) {
    options.scan_max_hz = sample_rate / 2.0 - 100.0;
  }

  std::vector<unsigned char> cache_buf(1024 * 64, 0);
  RecvDataCacheInfo alsa_cache;
  RecvDataCacheInit(&alsa_cache, cache_buf.data(),
                    static_cast<unsigned int>(cache_buf.size()));

  void *alsa_handle = nullptr;
  int ret = duerwen_alsa_init(&alsa_handle, const_cast<char *>(pcm_device.c_str()),
                              channels, sample_rate, SND_PCM_STREAM_CAPTURE);
  if (ret != 0) {
    std::fprintf(stderr, "duerwen_alsa_init failed: %d\n", ret);
    return 1;
  }

  const auto *alsa_params = static_cast<const DuerWenAlsaParams *>(alsa_handle);
  const int alsa_period_frames =
      alsa_params && alsa_params->frames > 0
          ? static_cast<int>(alsa_params->frames)
          : processing_frame_samples;

  FeatureExtractor extractor(processing_frame_samples, sample_rate,
                             options.scan_min_hz, options.scan_max_hz);

  std::cout << "Whistle calibration started.\n"
            << "Audio: device=" << pcm_device << " channels=" << channels
            << " sample_rate=" << sample_rate
            << " frame_samples=" << processing_frame_samples << "\n"
            << "Scan band: " << options.scan_min_hz << "-"
            << options.scan_max_hz << " Hz\n\n";

  if (!options.no_prompt) {
    std::cout << "Keep the robot in the normal quiet match environment, then "
                 "press Enter.\n";
    std::string line;
    std::getline(std::cin, line);
  }
  auto noise_features =
      capturePhase(alsa_handle, channels, alsa_period_frames, sample_rate,
                   processing_frame_samples, options.noise_seconds, &extractor,
                   "Noise");

  if (!g_running || noise_features.empty()) {
    duerwen_alsa_unit(alsa_handle);
    return 1;
  }

  if (!options.no_prompt) {
    std::cout << "\nNow blow/squeeze the whistle 3-5 times during the next "
              << options.whistle_seconds
              << " seconds. Press Enter when ready.\n";
    std::string line;
    std::getline(std::cin, line);
  }
  auto whistle_features =
      capturePhase(alsa_handle, channels, alsa_period_frames, sample_rate,
                   processing_frame_samples, options.whistle_seconds,
                   &extractor, "Whistle");

  duerwen_alsa_unit(alsa_handle);

  if (!g_running || whistle_features.empty()) {
    return 1;
  }

  const PhaseStats noise_scan_stats =
      computeStats(noise_features, processing_frame_samples, sample_rate,
                   options.scan_min_hz, options.scan_max_hz);
  auto candidates =
      selectWhistleCandidates(whistle_features, noise_scan_stats);

  std::vector<double> candidate_peak_hz;
  std::vector<double> candidate_rms;
  std::vector<double> candidate_peak_mag;
  candidate_peak_hz.reserve(candidates.size());
  candidate_rms.reserve(candidates.size());
  candidate_peak_mag.reserve(candidates.size());
  for (const auto *feature : candidates) {
    candidate_peak_hz.push_back(feature->peak_hz);
    candidate_rms.push_back(feature->rms);
    candidate_peak_mag.push_back(feature->peak_magnitude);
  }

  const double peak_hz_p10 = percentile(candidate_peak_hz, 0.10);
  const double peak_hz_p50 = percentile(candidate_peak_hz, 0.50);
  const double peak_hz_p90 = percentile(candidate_peak_hz, 0.90);

  RecommendedConfig recommended;
  recommended.min_peak_hz =
      std::max(options.scan_min_hz, roundDown(peak_hz_p10 - 200.0, 50.0));
  recommended.max_peak_hz =
      std::min(options.scan_max_hz, roundUp(peak_hz_p90 + 200.0, 50.0));
  if (recommended.max_peak_hz - recommended.min_peak_hz < 300.0) {
    recommended.min_peak_hz =
        std::max(options.scan_min_hz, roundDown(peak_hz_p50 - 200.0, 50.0));
    recommended.max_peak_hz =
        std::min(options.scan_max_hz, roundUp(peak_hz_p50 + 200.0, 50.0));
  }

  const PhaseStats noise_final_stats =
      computeStats(noise_features, processing_frame_samples, sample_rate,
                   recommended.min_peak_hz, recommended.max_peak_hz);

  std::vector<double> candidate_band_ratio;
  candidate_band_ratio.reserve(candidates.size());
  for (const auto *feature : candidates) {
    candidate_band_ratio.push_back(bandRatio(
        *feature, processing_frame_samples, sample_rate,
        recommended.min_peak_hz, recommended.max_peak_hz));
  }

  const double signal_rms_p10 = percentile(candidate_rms, 0.10);
  const double signal_peak_p10 = percentile(candidate_peak_mag, 0.10);
  const double signal_band_p10 = percentile(candidate_band_ratio, 0.10);
  const double signal_band_p50 = percentile(candidate_band_ratio, 0.50);

  recommended.min_rms =
      chooseThreshold(noise_final_stats.rms_p99, signal_rms_p10, 0.050, 0.70,
                      1.25);
  recommended.min_peak_magnitude =
      chooseThreshold(noise_final_stats.peak_p99, signal_peak_p10, 0.0005,
                      0.65, 1.50);
  recommended.min_band_ratio =
      chooseThreshold(noise_final_stats.band_p99, signal_band_p10, 0.080,
                      0.65, 1.30);
  recommended.min_band_ratio = std::min(recommended.min_band_ratio, 0.85);

  std::cout << "\nSummary\n";
  std::cout << "  Noise blocks: " << noise_features.size()
            << ", whistle blocks: " << whistle_features.size()
            << ", selected whistle-like blocks: " << candidates.size()
            << "\n";
  std::cout << "  Whistle peak Hz p10/p50/p90: "
            << formatDouble(peak_hz_p10, 1) << " / "
            << formatDouble(peak_hz_p50, 1) << " / "
            << formatDouble(peak_hz_p90, 1) << "\n";
  std::cout << "  Noise p99 rms/peak/band: "
            << formatDouble(noise_final_stats.rms_p99, 4) << " / "
            << formatDouble(noise_final_stats.peak_p99, 6) << " / "
            << formatDouble(noise_final_stats.band_p99, 3) << "\n";
  std::cout << "  Whistle p10 rms/peak/band: "
            << formatDouble(signal_rms_p10, 4) << " / "
            << formatDouble(signal_peak_p10, 6) << " / "
            << formatDouble(signal_band_p10, 3) << "\n";

  if (signal_peak_p10 < noise_final_stats.peak_p99 * 1.5 ||
      signal_band_p50 < noise_final_stats.band_p99 * 1.2) {
    std::cout << "\nWarning: whistle/noise separation looks weak. Re-run in a "
                 "quieter setup, move the whistle closer, or use stricter "
                 "required_blocks.\n";
  }

  const std::string snippet = yamlSnippet(recommended);
  std::cout << "\nRecommended detection.mono_spectral block:\n\n"
            << snippet << "\n";

  YAML::Node output_config = input_config;
  YAML::Node output_params = paramsRootForWrite(output_config);
  YAML::Node mono = output_params["detection"]["mono_spectral"];
  mono["enable"] = true;
  mono["min_rms"] = recommended.min_rms;
  mono["min_peak_hz"] = recommended.min_peak_hz;
  mono["max_peak_hz"] = recommended.max_peak_hz;
  mono["min_peak_magnitude"] = recommended.min_peak_magnitude;
  mono["min_band_ratio"] = recommended.min_band_ratio;
  mono["required_blocks"] = recommended.required_blocks;
  mono["cooldown_blocks"] = recommended.cooldown_blocks;
  mono["log_features"] = false;
  output_params["detection"]["mono_spectral"] = mono;

  YAML::Node calibration = output_params["calibration"];
  calibration["whistle"]["calibration_time"] = currentTimestamp();
  calibration["whistle"]["noise_seconds"] = options.noise_seconds;
  calibration["whistle"]["whistle_seconds"] = options.whistle_seconds;
  calibration["whistle"]["noise_p99_rms"] = noise_final_stats.rms_p99;
  calibration["whistle"]["noise_p99_peak"] = noise_final_stats.peak_p99;
  calibration["whistle"]["noise_p99_band_ratio"] = noise_final_stats.band_p99;
  calibration["whistle"]["whistle_p10_rms"] = signal_rms_p10;
  calibration["whistle"]["whistle_p10_peak"] = signal_peak_p10;
  calibration["whistle"]["whistle_p10_band_ratio"] = signal_band_p10;
  calibration["whistle"]["whistle_peak_hz_p50"] = peak_hz_p50;
  output_params["calibration"] = calibration;

  const std::string timestamp = currentTimestamp();
  const std::string result_path =
      options.config_path + ".calibration_res_" + timestamp;
  if (!writeYamlFile(result_path, output_config)) {
    std::cerr << "Cannot write result file: " << result_path << "\n";
    return 1;
  }
  std::cout << "Saved calibration result to " << result_path << "\n";

  if (!options.no_overwrite) {
    bool overwrite = options.assume_yes;
    if (!overwrite) {
      overwrite = askYesNo("overwrite input config with new config?");
    }
    if (overwrite) {
      const std::string backup_path =
          options.config_path + ".input_backup_" + timestamp;
      if (!writeYamlFile(backup_path, input_config)) {
        std::cerr << "Cannot write backup file: " << backup_path << "\n";
        return 1;
      }
      if (!writeYamlFile(options.config_path, output_config)) {
        std::cerr << "Cannot overwrite input config: " << options.config_path
                  << "\n";
        return 1;
      }
      std::cout << "Backed up original config to " << backup_path << "\n";
      std::cout << "Overwrote " << options.config_path << "\n";
    } else {
      std::cout << "Input config was not overwritten.\n";
    }
  }

  return 0;
}
