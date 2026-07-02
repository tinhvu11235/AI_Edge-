cmake_minimum_required(VERSION 3.16)

project(edge_voice_pipeline LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(EDGEVOICE_WITH_ALSA "Build ALSA audio sink" ON)

add_executable(edge_voice_pipeline
  src/main.cpp
)

find_package(Threads REQUIRED)
target_link_libraries(edge_voice_pipeline PRIVATE Threads::Threads)

if(MSVC)
  target_compile_options(edge_voice_pipeline PRIVATE /W4)
else()
  target_compile_options(edge_voice_pipeline PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(EDGEVOICE_WITH_ALSA)
  find_package(ALSA REQUIRED)
  target_compile_definitions(edge_voice_pipeline PRIVATE EDGEVOICE_HAS_ALSA=1)
  target_link_libraries(edge_voice_pipeline PRIVATE ALSA::ALSA)
else()
  target_compile_definitions(edge_voice_pipeline PRIVATE EDGEVOICE_HAS_ALSA=0)
endif()
