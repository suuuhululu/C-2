cmake_minimum_required(VERSION 3.8)
project(c2_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(geometry_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/GeneratePath.action"
  "action/ExecuteProcess.action"
  "srv/StopProcess.srv"
  "msg/ProcessState.msg"
  "msg/ProcessEvent.msg"
  DEPENDENCIES builtin_interfaces geometry_msgs
)

ament_export_dependencies(rosidl_default_runtime)

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(generated_contract test/test_generated_contract.py TIMEOUT 60)
endif()

ament_package()
