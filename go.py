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

# print('hello')

# import matplotlib.pyplot as plt

# # 예시 데이터
# x = [1, 2, 3, 4, 5]
# y = [1, 4, 9, 16, 25]

# # 그래프 그리기
# plt.plot(x, y)
# plt.title("Sample Line Plot")
# plt.xlabel("X Axis")
# plt.ylabel("Y Axis")

# # 그리드 표시 (선택)
# plt.grid(True, linestyle="--", linewidth=0.5)

# # 화면에 출력
# plt.show()




#========================================================================
# src/util.py
message = "src/util.py에서 온 메시지입니다!"

def say_hello(name):
    return f"{name}님, 환영합니다!"


# main.py
from src import utils

print(utils.message)
print(utils.say_hello("재우"))
