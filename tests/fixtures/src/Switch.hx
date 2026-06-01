// Control-flow fixture: switch with multiple cases and break-like exits
class Switch {
    static function main() {
        testSwitch(1);
        testSwitch(2);
        testSwitch(3);
        testSwitch(99);
    }

    // Simple integer switch with discrete break-like exits
    static function testSwitch(n:Int):String {
        var result = "";
        switch (n) {
            case 1:
                result = "one";
            case 2:
                result = "two";
            case 3:
                result = "three";
            default:
                result = "unknown";
        }
        trace(result);
        return result;
    }
}
