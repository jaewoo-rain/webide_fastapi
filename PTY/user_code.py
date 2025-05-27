
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
