class Shapes {
    static function main() {
        var c = new Circle(5);
        var r = new Rect(3, 4);
        trace("Area circle: " + c.area());
        trace("Area rect: " + r.area());
        var f = Flag.Active;
        trace(f);
    }
}

interface Shape {
    function area():Float;
}

class Circle implements Shape {
    var r:Float;
    public function new(r:Float) { this.r = r; }
    public function area():Float { return Math.PI * r * r; }
}

class Rect implements Shape {
    var w:Float;
    var h:Float;
    public function new(w:Float, h:Float) {
        this.w = w; this.h = h;
    }
    public function area():Float { return w * h; }
}

enum Flag {
    Active;
    Inactive;
    Pending;
}
