// Одна и та же деталь для теста трёх CAD: плита 80×60×6, два отверстия ø5.
// Ровно та же геометрия, что в plate.f3d (ФОРМА), plate_part.py (FreeCAD)
// и в эталонном расчёте: 28,8 − 0,236 = 28,564 см³.
$fn = 96;

difference() {
    cube([80, 60, 6], center = true);
    for (x = [-28, 28]) {
        translate([x, 0, 0]) cylinder(h = 20, r = 2.5, center = true);
    }
}
