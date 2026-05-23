// Classes, enums, inheritance
enum Color {
    Red;
    Green;
    Blue;
    Rgb(r:Int, g:Int, b:Int);
}

class Point {
    public var x:Float;
    public var y:Float;
    public function new(x:Float, y:Float) {
        this.x = x;
        this.y = y;
    }
    public function length():Float {
        return Math.sqrt(x * x + y * y);
    }
}

class Shape {
    public function new() {}
    public function area():Float { return 0; }
}

class Circle extends Shape {
    var radius:Float;
    public function new(r:Float) { super(); radius = r; }
    override public function area():Float {
        return Math.PI * radius * radius;
    }
}

class Classes {
    static function main() {
        var p = new Point(3, 4);
        trace("Length: " + p.length());
        var c = new Circle(5);
        trace("Area: " + c.area());
        var col:Color = Color.Rgb(255, 0, 128);
        trace(col);
    }
}
