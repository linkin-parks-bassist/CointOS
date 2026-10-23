#include <fcntl.h>
#include <sys/file.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

#include <cstring>
#include <filesystem>
#include <iostream>
#include <stdexcept>

#include "control.hpp"
#include "src/cli/serve/inference_backend.hpp"
#include "transport.hpp"

int main(int argc, char** argv) {
  int listener = -1, lock = -1;
  bool bound = false;
  try {
    if (argc != 7 && argc != 11)
      throw std::invalid_argument(
          "usage: gufo-control MODEL SOCKET CONTEXT LANES SNAPSHOTS SHA256 "
          "[DRAFT DRAFT_SHA256 DRAFT_TOKENS POLICY]");
    const std::filesystem::path socket_path(argv[2]);
    if (socket_path.string().size() >= sizeof(sockaddr_un::sun_path))
      throw std::invalid_argument("socket path too long");
    std::filesystem::create_directories(socket_path.parent_path());
    struct stat parent {};
    if (stat(socket_path.parent_path().c_str(), &parent) ||
        parent.st_uid != getuid() || (parent.st_mode & 0077))
      throw std::runtime_error(
          "socket directory must be owned by this user and mode 0700");
    const auto lock_path = socket_path.string() + ".lock";
    lock = open(lock_path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW,
                0600);
    if (lock < 0 || flock(lock, LOCK_EX | LOCK_NB))
      throw std::runtime_error("control process already running");
    // Only the lock owner can replace a socket left by an interrupted process.
    struct stat old {};
    if (lstat(socket_path.c_str(), &old) == 0) {
      if (!S_ISSOCK(old.st_mode) || old.st_uid != getuid())
        throw std::runtime_error("refusing to replace a non-owned socket");
      std::filesystem::remove(socket_path);
    }
    if (cointos::FileSha256(argv[1]) != argv[6])
      throw std::runtime_error("model SHA256 mismatch");
    const auto context = std::stoul(argv[3]), lanes = std::stoul(argv[4]);
    if (context < 2 || context > UINT32_MAX || lanes == 0)
      throw std::invalid_argument("invalid model shape");
    gufo::server::InferenceBackend backend;
    gufo::server::TextSpeculativeConfig speculation;
    std::string identity =
        std::string(argv[6]) + ":1f97092333af10f29887b098d9cb8a041610004a";
    if (argc == 11) {
      if (cointos::FileSha256(argv[7]) != argv[8])
        throw std::runtime_error("draft SHA256 mismatch");
      const auto draft_tokens = std::stoul(argv[9]);
      if (draft_tokens < 1 || draft_tokens > 7)
        throw std::invalid_argument("DFlash draft tokens must be 1 through 7");
      speculation.backend = gufo::server::TextSpeculativeBackend::kDFlash;
      speculation.draft_model_path = argv[7];
      speculation.max_draft_tokens = draft_tokens;
      speculation.dflash_policy =
          gufo::speculative::ParseDFlashDraftPolicy(argv[10]);
      identity +=
          ":dflash:" + std::string(argv[8]) + ":" + argv[9] + ":" + argv[10];
    }
    std::string error;
    if (!backend.load(argv[1], &error, context, lanes, {}, {}, speculation))
      throw std::runtime_error(error);
    cointos::Control control(backend.release_runner(), lanes, argv[5],
                             identity);
    listener = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (listener < 0)
      throw std::runtime_error("cannot create socket");
    sockaddr_un address{};
    address.sun_family = AF_UNIX;
    std::memcpy(address.sun_path, argv[2], std::strlen(argv[2]) + 1);
    mode_t previous = umask(0077);
    const int binding =
        bind(listener, reinterpret_cast<sockaddr*>(&address), sizeof(address));
    umask(previous);
    if (binding)
      throw std::runtime_error("cannot bind control socket");
    bound = true;
    if (listen(listener, SOMAXCONN))
      throw std::runtime_error("cannot listen");
    std::cout << "ready\n" << std::flush;
    cointos::ServeControl(listener, control);
    close(listener);
    listener = -1;
    std::filesystem::remove(socket_path);
    close(lock);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "gufo-control: " << error.what() << '\n';
    if (listener >= 0)
      close(listener);
    if (bound)
      std::filesystem::remove(argv[2]);
    if (lock >= 0)
      close(lock);
    return 1;
  }
}
