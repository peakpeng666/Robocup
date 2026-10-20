// Uses the very same wrapper compiled into SimRobot, with bounded inference.
#define BH_ONNX_VALIDATOR
#include "CompiledNN2ONNX/CompiledNN.h"
#include <cmath>
#include <iomanip>

int main(int argc, char** argv)
{
  if(argc != 4) return 2;
  NeuralNetworkONNX::Model model(argv[1]);
  NeuralNetworkONNX::CompiledNN network;
  const auto start = std::chrono::steady_clock::now();
  network.compile(model);
  auto input = network.input(0);
  if(std::string(argv[2]) == "synthetic")
    for(size_t i = 0; i < input.size(); ++i)
      input[i] = static_cast<float>((i * 37 + i / 544) % 256);
  else
  {
    std::ifstream stream(argv[2], std::ios::binary | std::ios::ate);
    if(!stream || stream.tellg() != static_cast<std::streamoff>(input.size() * sizeof(float))) return 3;
    stream.seekg(0);
    stream.read(reinterpret_cast<char*>(input.data()), input.size() * sizeof(float));
    if(!stream) return 4;
  }
  for(int i = 0; i < 3; ++i) network.apply();
  const auto ready = std::chrono::steady_clock::now();
  for(int i = 0; i < 20; ++i) network.apply();
  const auto done = std::chrono::steady_clock::now();
  auto output = network.output(0);
  for(float x : output) if(!std::isfinite(x)) return 5;
  std::ofstream stream(argv[3], std::ios::binary);
  stream.write(reinterpret_cast<const char*>(output.data()), output.size() * sizeof(float));
  if(!stream) return 6;
  std::cout << std::setprecision(9) << "{\"input_values\":" << input.size()
            << ",\"output_values\":" << output.size() << ",\"setup_ms\":"
            << std::chrono::duration<double, std::milli>(ready - start).count()
            << ",\"mean_apply_ms\":" << std::chrono::duration<double, std::milli>(done - ready).count() / 20 << "}\n";
}
