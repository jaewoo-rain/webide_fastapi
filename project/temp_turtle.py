# -*- coding: utf-8 -*-
<<<<<<< HEAD
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
=======
import turtle

screen = turtle.Screen()
screen.bgcolor("black")

star = turtle.Turtle()
star.color("yellow")
star.speed(3)

def draw_star(size):
    for i in range(5):
        star.forward(size)
        star.right(144)

for i in range(5):
    draw_star(100)
    star.penup()
    star.forward(150)
    star.right(144)
    star.pendown()

turtle.done()
>>>>>>> 983c151c0a9f99f4313e79908f80bdaaec0c6d25
