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
namespace cointos {
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
          } else
            response["result"] = control.Call(request);
        }
      } catch (const std::exception& exception) {
        response["error"] = exception.what();
      }
      const auto bytes = response.dump() + "\n";
      std::size_t offset = 0;
      while (offset < bytes.size()) {
        auto n = send(client, bytes.data() + offset, bytes.size() - offset,
                      MSG_NOSIGNAL);
        if (n <= 0)
          break;
        offset += n;
      }
      close(client);
    }));
  }
  for (auto& client : clients)
    client.get();
}
}  // namespace cointos
