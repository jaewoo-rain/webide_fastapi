# -*- coding: utf-8 -*-
<<<<<<< HEAD
import turtle

screen = turtle.Screen()
screen.title("Turtle Spiral Demo")
screen.bgcolor("white")
screen.setup(width=600, height=600)

spiral = turtle.Turtle()
spiral.speed(0)       
spiral.width(2)       

colors = ["red", "orange", "yellow", "green", "blue", "purple"]

for i in range(360):
    spiral.pencolor(colors[i % len(colors)])
    spiral.forward(i * 0.5)
    spiral.right(59)

screen.exitonclick()

print('hello')
=======
import jaewoo

print("jaewoo")
>>>>>>> e78b4b52879c010fb0ff2ccc05525f21cbf494aa
