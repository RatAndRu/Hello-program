// ФОРМА 3D → OpenSCAD, режим script: параметрическая запись
// правьте числа и модули; непереведённые команды заменены polyhedron
$fn = 64;
// плита0 = box size=[80,60,6] center=да
module plita0() {
  translate([0, 0, 0]) cube([80, 60, 6], center = true);
}

// h1 = cylinder radius=2.5 height=20 at=[-28,0,-6]
module h1() {
  translate([-28, 0, 4]) cylinder(h = 20, r = 2.5, center = true);
}

// h2 = cylinder radius=2.5 height=20 at=[28,0,-6]
module h2() {
  translate([28, 0, 4]) cylinder(h = 20, r = 2.5, center = true);
}

// плита = difference
module plita() {
  difference() {
    plita0();
    h1();
    h2();
  }
}

plita();   // плита
