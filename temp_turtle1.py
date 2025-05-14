import requests

code1 = """
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
"""

code2 = """
import turtle

screen = turtle.Screen()
screen.bgcolor("white")
screen.setup(width=900, height=600)

t = turtle.Turtle()
t.shape("turtle")
t.color("blue")
t.speed(10)

left_edge = -screen.window_width() // 2
right_edge = screen.window_width() // 2

def move_turtle():
    t.forward(10)
    
    if t.xcor() > right_edge:
        t.setx(right_edge)
        t.right(180)
    elif t.xcor() < left_edge:
        t.setx(left_edge)
        t.right(180)
    
    screen.ontimer(move_turtle, 20)

move_turtle()

screen.mainloop()

"""

res = requests.post("http://localhost:5000/run", json={"code": code1})
print(res.json())
