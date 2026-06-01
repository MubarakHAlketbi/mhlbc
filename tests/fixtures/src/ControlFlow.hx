// Control-flow fixture: if/else-if/else chain, while loop with break, for loop with continue
class ControlFlow {
    static function main() {
        testIfElse(5);
        testIfElse(15);
        testIfElse(50);
        testLoopBreak(3);
        testLoopContinue();
    }

    // if / else-if / else chain
    static function testIfElse(x:Int):String {
        var result = "";
        if (x < 10) {
            result = "small";
        } else if (x < 20) {
            result = "medium";
        } else {
            result = "large";
        }
        trace(result);
        return result;
    }

    // While loop with break
    static function testLoopBreak(maxIter:Int):Int {
        var i = 0;
        var sum = 0;
        while (true) {
            sum += i;
            i++;
            if (i > maxIter) {
                break;
            }
        }
        trace("sum=" + sum);
        return sum;
    }

    // For loop with continue
    static function testLoopContinue():Int {
        var sum = 0;
        for (i in 0...10) {
            if (i % 2 == 0) {
                continue;
            }
            sum += i;
        }
        trace("odd sum=" + sum);
        return sum;
    }
}
