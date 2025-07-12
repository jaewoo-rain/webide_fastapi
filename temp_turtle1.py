import requests
code = """
import turtle

# 화면 설정
screen = turtle.Screen()
screen.title("Turtle Spiral Demo")
screen.bgcolor("white")
screen.setup(width=600, height=600)

# 거북이(터틀) 설정
spiral = turtle.Turtle()
spiral.speed(0)          # 최고 속도
spiral.width(2)          # 선 굵기

colors = ["red", "orange", "yellow", "green", "blue", "purple"]

# 나선 그리기
for i in range(360):
    spiral.pencolor(colors[i % len(colors)])
    spiral.forward(i * 0.5)
    spiral.right(59)

# 클릭하면 종료
screen.exitonclick()
"""

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

res = requests.post("http://localhost:8000/run-gui", json={"code": code1})
print(res.json())
