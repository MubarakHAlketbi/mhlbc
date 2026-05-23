class Natives {
    static function main() {
        var s = "Hello, World!";
        trace(s.toUpperCase());
        trace(s.toLowerCase());
        trace(s.length);
        trace(s.charAt(0));
        trace(s.substr(4, 2));

        var arr = [1, 2, 3, 4, 5];
        arr.push(6);
        trace(arr.length);
        trace(arr.pop());
        trace(arr.shift());

        var m = ["key1" => "val1", "key2" => "val2"];
        trace(m.get("key1"));
    }
}
