Problem:    production_plan
Rows:       4
Columns:    3
Non-zeros:  12
Status:     OPTIMAL
Objective:  obj = 1533.333333 (MAXimum)

   No.   Row name   St   Activity     Lower bound   Upper bound    Marginal
------ ------------ -- ------------- ------------- ------------- -------------
     1 obj          B        1533.33                             
     2 DEV_I        NU            60                          60       23.3333 
     3 DEV_II       NU            40                          40       3.33333 
     4 DEV_III      B        23.3333                          50 

   No. Column name  St   Activity     Lower bound   Upper bound    Marginal
------ ------------ -- ------------- ------------- ------------- -------------
     1 XA           NL             0             0                         -10 
     2 XB           B        6.66667             0               
     3 XC           B        26.6667             0               

Karush-Kuhn-Tucker optimality conditions:

KKT.PE: max.abs.err = 0.00e+00 on row 0
        max.rel.err = 0.00e+00 on row 0
        High quality

KKT.PB: max.abs.err = 0.00e+00 on row 0
        max.rel.err = 0.00e+00 on row 0
        High quality

KKT.DE: max.abs.err = 0.00e+00 on column 0
        max.rel.err = 0.00e+00 on column 0
        High quality

KKT.DB: max.abs.err = 0.00e+00 on row 0
        max.rel.err = 0.00e+00 on row 0
        High quality

End of output
