class Enums {
    static function main() {
        var a = Option.Some(42);
        var b = Option.None;
        var result = switch(a) {
            case Option.Some(v): "value: " + v;
            case Option.None: "no value";
        }
        trace(result);

        var colors = [Color.Red, Color.Green, Color.Blue];
        for (c in colors) {
            trace(switch(c) {
                case Color.Red: 0xFF0000;
                case Color.Green: 0x00FF00;
                case Color.Blue: 0x0000FF;
            });
        }
    }
}

enum Option<T> {
    Some(v:T);
    None;
}

@:enum abstract Color(Int) {
    var Red = 0xFF0000;
    var Green = 0x00FF00;
    var Blue = 0x0000FF;
}
