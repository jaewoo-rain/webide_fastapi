# import turtle

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

print('hello')