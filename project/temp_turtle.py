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