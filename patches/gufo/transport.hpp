#pragma once
#include "control.hpp"
namespace cointos {
// Serialize mutable model operations; CPU metadata and health stay independent.
void ServeControl(int listener, Control& control);
}  // namespace cointos
