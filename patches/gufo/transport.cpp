#include "transport.hpp"

#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <future>
#include <mutex>
#include <stdexcept>
#include <string_view>
namespace cointos {
namespace {
bool SendAll(int socket, std::string_view bytes) {
  std::size_t offset = 0;
  while (offset < bytes.size()) {
    const auto n = send(socket, bytes.data() + offset, bytes.size() - offset,
                        MSG_NOSIGNAL);
    if (n <= 0)
      return false;
    offset += static_cast<std::size_t>(n);
  }
  return true;
}
}  // namespace

void ServeControl(int listener, Control& control) {
  std::atomic<bool> running{true};
  std::mutex owner;
  std::mutex metadata_owner;
  const auto info = control.Call(gufo::json::parse("{\"op\":\"info\"}"));
  std::vector<std::future<void>> clients;
  while (running.load()) {
    const int client = accept4(listener, nullptr, nullptr, SOCK_CLOEXEC);
    if (client < 0) {
      if (!running.load())
        break;
      if (errno == EINTR)
        continue;
      throw std::runtime_error("accept failed");
    }
    // Observability must not wait behind a long snapshot or inference step.
    // Mutable model operations have one owner. Immutable tokenizer/template
    // requests have a separate CPU owner so replies/admission do not queue
    // behind inference or snapshot transfers.
    clients.erase(std::remove_if(clients.begin(), clients.end(),
                                 [](auto& task) {
                                   if (task.wait_for(std::chrono::seconds(0)) !=
                                       std::future_status::ready)
                                     return false;
                                   task.get();
                                   return true;
                                 }),
                  clients.end());
    clients.push_back(std::async(std::launch::async, [&, client] {
      std::string line;
      char buffer[16384];
      while (line.find('\n') == std::string::npos) {
        auto n = read(client, buffer, sizeof(buffer));
        if (n <= 0)
          break;
        line.append(buffer, n);
      }
      if (line.empty()) {
        close(client);
        return;
      }
      gufo::json::Value response = gufo::json::Value::object();
      try {
        auto request = gufo::json::parse(line);
        if (request.member_str("op") == "info")
          response["result"] = info;
        else if (Control::IsMetadata(request.member_str("op"))) {
          const std::lock_guard<std::mutex> lock_metadata(metadata_owner);
          response["result"] = control.Metadata(request);
        } else {
          const std::lock_guard<std::mutex> lock_owner(owner);
          if (request.member_str("op") == "shutdown") {
            running.store(false);
            shutdown(listener, SHUT_RDWR);
            response["ok"] = true;
          } else {
            const auto* stream = request.find("stream");
            const bool streaming = stream && stream->is_bool() &&
                                   stream->as_bool();
            Control::Emit emit;
            if (streaming)
              emit = [&](const gufo::json::Value& frame) {
                auto wrapper = gufo::json::Value::object();
                wrapper["stream"] = frame;
                SendAll(client, wrapper.dump() + "\n");
              };
            response["result"] = control.Call(request, emit);
          }
        }
      } catch (const std::exception& exception) {
        response["error"] = exception.what();
      }
      SendAll(client, response.dump() + "\n");
      close(client);
    }));
  }
  for (auto& client : clients)
    client.get();
}
}  // namespace cointos
