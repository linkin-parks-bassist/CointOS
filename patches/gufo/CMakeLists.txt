set(COINTOS_RUNNER_SOURCES
  ${PROJECT_SOURCE_DIR}/src/cli/serve/text_model_runner.cpp
  ${PROJECT_SOURCE_DIR}/src/cli/serve/continuation_cache.cpp
  ${PROJECT_SOURCE_DIR}/src/cli/serve/continuation_disk_store.cpp
  ${PROJECT_SOURCE_DIR}/src/cli/serve/component_text_cache.cpp)
add_library(cointos_gufo_control STATIC control.cpp transport.cpp ${COINTOS_RUNNER_SOURCES})
target_link_libraries(cointos_gufo_control PUBLIC gufo_http gufo_cache gufo_core gufo_logging)
add_library(cointos_gufo_backend STATIC
  ${PROJECT_SOURCE_DIR}/src/cli/serve/inference_backend.cpp
  ${PROJECT_SOURCE_DIR}/src/cli/serve/text_generation_scheduler.cpp)
target_link_libraries(cointos_gufo_backend PUBLIC cointos_gufo_control gufo_diagnostics gufo_llm_cli CURL::libcurl)
add_executable(gufo-control main.cpp)
target_link_libraries(gufo-control PRIVATE cointos_gufo_backend)
if (ENGINE_ENABLE_HIP)
  target_link_libraries(cointos_gufo_backend PUBLIC gufo_cache_hip gufo_deepseek_v4_flash)
endif()
if (BUILD_TESTING)
  add_executable(cointos_gufo_control_test test.cpp)
  target_link_libraries(cointos_gufo_control_test PRIVATE cointos_gufo_control)
  add_test(NAME cointos_gufo_control_test COMMAND cointos_gufo_control_test)
  set_tests_properties(cointos_gufo_control_test PROPERTIES TIMEOUT 30)
endif()
if (BUILD_TESTING AND ENGINE_ENABLE_HIP)
  add_executable(cointos_gufo_gpu_test gpu_test.cpp)
  target_link_libraries(cointos_gufo_gpu_test PRIVATE cointos_gufo_backend)
  add_test(NAME cointos_gufo_gpu_test COMMAND cointos_gufo_gpu_test)
  set_tests_properties(cointos_gufo_gpu_test PROPERTIES LABELS "gpu;server;state" TIMEOUT 120)
endif()
# Standalone source builds can use an isolated ROCm prefix outside ld.so's paths.
if (ENGINE_ENABLE_HIP)
  foreach(control_target gufo-control cointos_gufo_control_test cointos_gufo_gpu_test)
    if (TARGET ${control_target})
      set_property(TARGET ${control_target} APPEND PROPERTY BUILD_RPATH
        "${CMAKE_HIP_COMPILER_ROCM_ROOT}/lib")
    endif()
  endforeach()
endif()
