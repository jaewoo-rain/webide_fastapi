# -*- coding: utf-8 -*-
# import turtle

# ȭ�� ����
screen = turtle.Screen()
screen.title("Turtle Spiral Demo")
screen.bgcolor("white")
screen.setup(width=600, height=600)

# �ź���(��Ʋ) ����
spiral = turtle.Turtle()
spiral.speed(0)          # �ְ� �ӵ�
spiral.width(2)          # �� ����

colors = ["red", "orange", "yellow", "green", "blue", "purple"]

# ���� �׸���
for i in range(360):
    spiral.pencolor(colors[i % len(colors)])
    spiral.forward(i * 0.5)
    spiral.right(59)

# Ŭ���ϸ� ����
screen.exitonclick()

print('hello')