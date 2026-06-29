from mistyPy.Robot import Robot
from mistyPy.Events import Events
import time
import math

misty = Robot("10.42.0.197")
misty.change_led(0, 255, 0)
misty.move_head(0, 0, 0)

#modes
turn_in_place = True
follow_human = True

#constants
yaw_left = 81.36
yaw_right = -85.37
pitch_up = -40.10
pitch_down = 26.92

#variables
curr_head_pitch = 0
curr_head_yaw = 0

#Event handler for getting the current head position
def curr_position(data):
    global curr_head_pitch, curr_head_yaw
    if data["message"]["sensorId"] == "ahp":
        curr_head_pitch = data["message"]["value"]
        print(curr_head_pitch)
    if data["message"]["sensorId"] == "ahy":
        curr_head_yaw = data["message"]["value"]
        print(curr_head_yaw)

def get_pos():
    misty.register_event(event_name="get_curr_position", event_type= Events.ActuatorPosition, keep_alive= True, callback_function=curr_position)
    time.sleep(0.25)
    misty.unregister_event(event_name="get_curr_position")

# Event handler for person detection
def person_detection(data):
    print(data)
    if data["message"]["confidence"] >= 0.6:
        width_of_human = data["message"]["imageLocationRight"] - data["message"]["imageLocationLeft"]
        x_error = (160.0 - (data["message"]["imageLocationLeft"] + data["message"]["imageLocationRight"]) / 2.0) / 160.0
        # Use this for non-human tracking
        # y_error = (160.0 - ((data["message"]["imageLocationTop"] + data["message"]["imageLocationBottom"]) / 2.0)) / 160.0
        
        #Use this for human tracking
        y_error = (160.0 - 0.8 * data["message"]["imageLocationTop"] - 0.2 * data["message"]["imageLocationBottom"]) / 160.0

        threshold = max((0.3 if turn_in_place or follow_human else 0.2), (321.0 - width_of_human) / 1000.0)
        damper_gain = 5.0 if turn_in_place or follow_human else 7.0

        get_pos()
        actuate_to_yaw = curr_head_yaw + x_error * ((yaw_left - yaw_right) / damper_gain) if abs(x_error) > threshold else None
        actuate_to_pitch = curr_head_pitch - y_error * ((pitch_down - pitch_up) / 3.0) if abs(y_error) > threshold else None

        linear_velocity = 0
        angular_velocity = 0

        if actuate_to_yaw and abs(actuate_to_yaw) > 15 and (turn_in_place or follow_human):
            angular_velocity = math.copysign(min(abs(actuate_to_yaw) * 0.6, 25), actuate_to_yaw)

        if angular_velocity != 0:
            if math.copysign(1, actuate_to_yaw - curr_head_yaw) == math.copysign(1, angular_velocity):
                if abs(actuate_to_yaw) > 40:
                    actuate_to_yaw /= 1.5
            else:
                actuate_to_yaw = 0
                angular_velocity = 0
                if not follow_human:
                    misty.stop()

        if follow_human:
            if angular_velocity == 0:
                linear_velocity = (130 - width_of_human) * 0.5
                linear_velocity = min(abs(linear_velocity), 20) * math.copysign(1, linear_velocity)
                linear_velocity = linear_velocity if abs(linear_velocity) > 5 else 0
                misty.change_led(0, 255, 255)

        misty.move_head(actuate_to_pitch, None, actuate_to_yaw)
        if turn_in_place or follow_human:
            misty.drive(linear_velocity, angular_velocity)

misty.start_object_detector(0.5, 0, 15)
misty.register_event(event_name="personDetection", event_type= Events.ObjectDetection, callback_function=person_detection, debounce=500, keep_alive=True)

misty.keep_alive()