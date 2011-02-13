#!/usr/bin/env python
'''
Created January, 2011

@author: Dr. Rainer Hessmer

  arduino.py - gateway to Arduino based differential drive base
  Copyright (c) 2011 Dr. Rainer Hessmer.  All right reserved.
  Borrowed heavily from Mike Feguson's ArbotiX base_controller.py code.

  Redistribution and use in source and binary forms, with or without
  modification, are permitted provided that the following conditions are met:
      * Redistributions of source code must retain the above copyright
        notice, this list of conditions and the following disclaimer.
      * Redistributions in binary form must reproduce the above copyright
        notice, this list of conditions and the following disclaimer in the
        documentation and/or other materials provided with the distribution.
      * Neither the name of the Vanadium Labs LLC nor the names of its 
        contributors may be used to endorse or promote products derived 
        from this software without specific prior written permission.
  
  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
  ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
  WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
  DISCLAIMED. IN NO EVENT SHALL VANADIUM LABS BE LIABLE FOR ANY DIRECT, INDIRECT,
  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
  LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA,
  OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
  LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE
  OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
  ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
'''

import roslib; roslib.load_manifest('ardros')
import rospy
import tf
import math
from math import sin, cos, pi
import sys

from geometry_msgs.msg import Quaternion
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from ardros.srv import *

from SerialDataGateway import SerialDataGateway

class Arduino(object):
	'''
	Helper class for communicating with an Arduino board over serial port
	'''

	def _HandleReceivedLine(self,  line):
		self._Counter = self._Counter + 1
		#rospy.logdebug(str(self._Counter) + " " + line)
		#if (self._Counter % 50 == 0):
		self._SerialPublisher.publish(String(str(self._Counter) + " " + line))
		if (len(line) > 0):
			lineParts = line.split('\t')
			if (lineParts[0] == 'o'):
				self._BroadcastOdometryInfo(lineParts)
				return
			if (lineParts[0] == "InitializeDifferentialDriveOdomParams"):
				# controller requesting initialization
				self._InitializeDifferentialDriveOdomParams()
				return
			if (lineParts[0] == "InitializeDifferentialDriveGains"):
				# controller requesting initialization
				self._InitializeDifferentialDriveGains()
				return
			if (lineParts[0] == "InitializeBatteryMonitor"):
				# controller requesting initialization
				self._InitializeBatteryMonitor()
				return

	def _BroadcastOdometryInfo(self, lineParts):
		partsCount = len(lineParts)
		#rospy.logwarn(partsCount)
		if (partsCount  < 6):
			pass
		
		try:
			x = float(lineParts[1])
			y = float(lineParts[2])
			theta = float(lineParts[3])
			
			vx = float(lineParts[4])
			omega = float(lineParts[5])
		
			#quaternion = tf.transformations.quaternion_about_axis(theta, (0,0,1))
			quaternion = Quaternion()
			quaternion.x = 0.0 
			quaternion.y = 0.0
			quaternion.z = sin(theta / 2.0)
			quaternion.w = cos(theta / 2.0)
			
			
			rosNow = rospy.Time.now()
			
			# first, we'll publish the transform over tf
			self._OdometryTransformBroadcaster.sendTransform(
				(x, y, 0), 
				(quaternion.x, quaternion.y, quaternion.z, quaternion.w),
				rosNow,
				"base_link",
				"odom"
				)

			# next, we'll publish the odometry message over ROS
			odometry = Odometry()
			odometry.header.frame_id = "odom"
			odometry.header.stamp = rosNow
			odometry.pose.pose.position.x = x
			odometry.pose.pose.position.y = y
			odometry.pose.pose.position.z = 0
			odometry.pose.pose.orientation = quaternion

			odometry.child_frame_id = "base_link"
			odometry.twist.twist.linear.x = vx
			odometry.twist.twist.linear.y = 0
			odometry.twist.twist.angular.z = omega

			self._OdometryPublisher.publish(odometry)
			
			#rospy.loginfo(odometry)
		
		except:
			rospy.logwarn("Unexpected error:" + str(sys.exc_info()[0]))


	def __init__(self, port="/dev/ttyUSB0", baudrate=115200):
		'''
		Initializes the receiver class. 
		port: The serial port to listen to.
		baudrate: Baud rate for the serial communication
		'''

		self._Counter = 0

		rospy.init_node('arduino')

		port = rospy.get_param("~port", "/dev/ttyUSB0")
		baudRate = int(rospy.get_param("~baudRate", 115200))

		rospy.loginfo("Starting with serial port: " + port + ", baud rate: " + str(baudRate))

		# subscriptions
		rospy.Subscriber("cmd_vel", Twist, self._HandleVelocityCommand)
		self._SerialPublisher = rospy.Publisher('serial', String)

		self._OdometryTransformBroadcaster = tf.TransformBroadcaster()
		self._OdometryPublisher = rospy.Publisher("odom", Odometry)
		
		self._SetDriveGainsService = rospy.Service('setDriveControlGains', SetDriveControlGains, self._HandleSetDriveGains)

		self._SerialDataGateway = SerialDataGateway(port, baudRate,  self._HandleReceivedLine)

	def Start(self):
		rospy.logdebug("Starting")
		self._SerialDataGateway.Start()

	def Stop(self):
		rospy.logdebug("Stopping")
		self._SerialDataGateway.Stop()
		
	def _HandleVelocityCommand(self, twistCommand):
		""" Handle movement requests. """
		v = twistCommand.linear.x        # m/s
		omega = twistCommand.angular.z      # rad/s
		rospy.loginfo("Handling twist command: " + str(v) + "," + str(omega))

		message = 's %d %d %d %d \r' % self._GetBaseAndExponents((v, omega))
		rospy.logdebug("Sending speed command message: " + message)
		self._SerialDataGateway.Write(message)

	def _InitializeDifferentialDriveOdomParams(self):
		wheelDiameter = rospy.get_param("~differentialDriveOdomParams/wheelDiameter", "0")
		trackWidth = rospy.get_param("~differentialDriveOdomParams/trackWidth", "0")
		countsPerRevolution = rospy.get_param("~differentialDriveOdomParams/countsPerRevolution", "0")

		wheelDiameterParts = self._GetBaseAndExponent(wheelDiameter)
		trackWidthParts = self._GetBaseAndExponent(trackWidth)

		message = 'DifferentialDriveOdomParams %d %d %d %d %d\r' % (wheelDiameterParts[0], wheelDiameterParts[1], trackWidthParts[0], trackWidthParts[1], countsPerRevolution)
		rospy.logdebug("Sending differential drive odom params message: " + message)
		self._SerialDataGateway.Write(message)

	def _InitializeDifferentialDriveGains(self):
		velocityPParam = rospy.get_param("~differentialDriveGains/velocityPParam", "0")
		velocityIParam = rospy.get_param("~differentialDriveGains/velocityIParam", "0")
		turnPParam = rospy.get_param("~differentialDriveGains/turnPParam", "0")
		turnIParam = rospy.get_param("~differentialDriveGains/turnIParam", "0")

		driveGains = (velocityPParam, velocityIParam, turnPParam, turnIParam)
		#rospy.loginfo(str(driveGains))
		self._WriteDriveGains(driveGains)

	def _HandleSetDriveGains(self, request):
		""" Handle the setting of the drive gains (PID). """
		
		# We persist the new values in the parameter server
		rospy.set_param("~differentialDriveGains", {'velocityPParam': request.velocityPParam, 'velocityPParam': request.velocityIParam, 'turnPParam': request.turnPParam, 'turnIParam': request.turnIParam})
		
		driveGains = (request.velocityPParam, request.velocityIParam, request.turnPParam, request.turnIParam)
		self._WriteDriveGains(driveGains)
		return SetDriveControlGainsResponse()

	def _WriteDriveGains(self, driveGains):
		""" Writes the drive gains (PID) to the Arduino controller. """
		rospy.logdebug("Handling 'SetDriveGains'; received parameters " + str(driveGains))
		
		message = 'DifferentialDriveGains %d %d %d %d %d %d %d %d\r' % self._GetBaseAndExponents(driveGains)
		rospy.logdebug("Sending differential drive gains message: " + message)
		self._SerialDataGateway.Write(message)

	def _InitializeBatteryMonitor(self):
		voltageTooLowlimit = rospy.get_param("~batteryMonitorParams/voltageTooLowlimit", "12.0")
		rospy.logdebug("Initializing battery monitor. voltageTooLowLimit = " + str(voltageTooLowlimit))

		message = 'BatteryMonitorParams %d %d\r' % self._GetBaseAndExponent(voltageTooLowlimit)
		rospy.logdebug("Sending battery monitor params message: " + message)
		self._SerialDataGateway.Write(message)

	def _GetBaseAndExponent(self, floatValue, resolution=4):
		'''
		Converts a float into a tuple holding two integers:
		The base, an integer with the number of digits equaling resolution.
		The exponent indicating what the base needs to multiplied with to get
		back the original float value with the specified resolution. 
		'''

		if (floatValue == 0.0):
			return (0, 0)
		else:
			exponent = int(1.0 + math.log10(abs(floatValue)))
			multiplier = math.pow(10, resolution - exponent)
			base = int(floatValue * multiplier)

			return(base, exponent - resolution)

	def _GetBaseAndExponents(self, floatValues, resolution=4):
		'''
		Converts a list or tuple of floats into a tuple holding two integers for each float:
		The base, an integer with the number of digits equaling resolution.
		The exponent indicating what the base needs to multiplied with to get
		back the original float value with the specified resolution. 
		'''

		baseAndExponents = []
		for floatValue in floatValues:
			baseAndExponent = self._GetBaseAndExponent(floatValue)
			baseAndExponents.append(baseAndExponent[0])
			baseAndExponents.append(baseAndExponent[1])

		return tuple(baseAndExponents)


if __name__ == '__main__':
	arduino = Arduino()
	try:
		arduino.Start()
		rospy.spin()

	except rospy.ROSInterruptException:
		arduino.Stop()


