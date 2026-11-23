      *****************************************************************
      * BENCALC - MONTHLY NUTRITION ASSISTANCE BENEFIT CALCULATOR
      * WRITTEN 1994 BY R. HALVORSEN, DIVISION OF AID PROGRAMS
      * MODIFIED 2003 - ADDED VETERAN SUPPLEMENT (REQ #4471)
      * MODIFIED 2011 - AK/HI COST OF LIVING ADJUSTMENT
      * NOTE: DO NOT CHANGE ROUNDING - AUDIT FINDING 2008-17
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BENCALC.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT APPLICANT-FILE ASSIGN TO "data/applicants.dat"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REPORT-FILE ASSIGN TO "out/report.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  APPLICANT-FILE.
       01  APPLICANT-REC.
           05  AP-ID               PIC X(8).
           05  AP-LAST-NAME        PIC X(15).
           05  AP-STATE            PIC X(2).
           05  AP-HH-SIZE          PIC 9(2).
           05  AP-INCOME           PIC 9(6)V99.
           05  AP-AGE              PIC 9(3).
           05  AP-DISABLED         PIC X.
           05  AP-VETERAN          PIC X.
       FD  REPORT-FILE.
       01  REPORT-LINE             PIC X(60).
       WORKING-STORAGE SECTION.
       01  WS-EOF                  PIC X VALUE "N".
       01  WS-THRESHOLD            PIC 9(6)V99.
       01  WS-LIMIT-130            PIC 9(6)V99.
       01  WS-LIMIT-200            PIC 9(6)V99.
       01  WS-MAX-ALLOT            PIC 9(5)V99.
       01  WS-NET-INCOME           PIC S9(6)V99.
       01  WS-CONTRIB              PIC 9(6)V99.
       01  WS-BENEFIT              PIC S9(6)V99.
       01  WS-STATUS               PIC X(8).
       01  WS-REASON               PIC X(4).
       01  WS-CNT-READ             PIC 9(5) VALUE 0.
       01  WS-CNT-ELIG             PIC 9(5) VALUE 0.
       01  WS-CNT-DENY             PIC 9(5) VALUE 0.
       01  WS-CNT-REJ              PIC 9(5) VALUE 0.
       01  WS-TOTAL-BEN            PIC 9(8)V99 VALUE 0.
       01  WS-OUT.
           05  OUT-ID              PIC X(8).
           05  FILLER              PIC X VALUE SPACE.
           05  OUT-STATUS          PIC X(8).
           05  FILLER              PIC X VALUE SPACE.
           05  OUT-BENEFIT         PIC ZZZ9.99.
           05  FILLER              PIC X VALUE SPACE.
           05  OUT-REASON          PIC X(4).
       01  WS-SUM-LINE.
           05  SUM-LABEL           PIC X(20).
           05  SUM-VALUE           PIC ZZZZZZZ9.99.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT APPLICANT-FILE
           OPEN OUTPUT REPORT-FILE
           PERFORM UNTIL WS-EOF = "Y"
               READ APPLICANT-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END PERFORM PROCESS-APPLICANT
               END-READ
           END-PERFORM
           PERFORM WRITE-SUMMARY
           CLOSE APPLICANT-FILE REPORT-FILE
           STOP RUN.

       PROCESS-APPLICANT.
           ADD 1 TO WS-CNT-READ
           MOVE 0 TO WS-BENEFIT
           MOVE SPACES TO WS-REASON
           IF AP-HH-SIZE IS NOT NUMERIC OR AP-INCOME IS NOT NUMERIC
              OR AP-AGE IS NOT NUMERIC OR AP-HH-SIZE = 0
               MOVE "REJECT" TO WS-STATUS
               MOVE "R01" TO WS-REASON
               ADD 1 TO WS-CNT-REJ
           ELSE
               PERFORM COMPUTE-THRESHOLD
               PERFORM DETERMINE-ELIGIBILITY
           END-IF
           PERFORM WRITE-DETAIL.

       COMPUTE-THRESHOLD.
           COMPUTE WS-THRESHOLD = 1580 + 560 * (AP-HH-SIZE - 1)
           IF AP-STATE = "AK"
               COMPUTE WS-THRESHOLD = WS-THRESHOLD * 1.25
           END-IF
           IF AP-STATE = "HI"
               COMPUTE WS-THRESHOLD = WS-THRESHOLD * 1.15
           END-IF
           COMPUTE WS-LIMIT-130 = WS-THRESHOLD * 1.30
           COMPUTE WS-LIMIT-200 = WS-THRESHOLD * 2.00.

       DETERMINE-ELIGIBILITY.
           IF AP-INCOME > WS-LIMIT-130
               IF AP-DISABLED = "Y" AND AP-INCOME NOT > WS-LIMIT-200
                   MOVE "D20" TO WS-REASON
                   PERFORM COMPUTE-BENEFIT
               ELSE
                   MOVE "DENIED" TO WS-STATUS
                   MOVE "I01" TO WS-REASON
                   ADD 1 TO WS-CNT-DENY
               END-IF
           ELSE
               PERFORM COMPUTE-BENEFIT
           END-IF.

       COMPUTE-BENEFIT.
           IF AP-HH-SIZE > 8
               COMPUTE WS-MAX-ALLOT = 290 + 240 * 7
                                     + 200 * (AP-HH-SIZE - 8)
           ELSE
               COMPUTE WS-MAX-ALLOT = 290 + 240 * (AP-HH-SIZE - 1)
           END-IF
           COMPUTE WS-NET-INCOME = AP-INCOME - 198
           IF WS-NET-INCOME < 0
               MOVE 0 TO WS-NET-INCOME
           END-IF
      *    TRUNCATES TO THE CENT - SEE AUDIT FINDING 2008-17
           COMPUTE WS-CONTRIB = WS-NET-INCOME * 0.30
           COMPUTE WS-BENEFIT = WS-MAX-ALLOT - WS-CONTRIB
           IF AP-VETERAN = "Y"
               ADD 50 TO WS-BENEFIT
           END-IF
           IF AP-AGE NOT < 60
               ADD 25 TO WS-BENEFIT
           END-IF
           IF WS-BENEFIT NOT > 0
               IF AP-HH-SIZE NOT > 2
                   MOVE 23 TO WS-BENEFIT
                   MOVE "M23" TO WS-REASON
               ELSE
                   MOVE 0 TO WS-BENEFIT
                   MOVE "DENIED" TO WS-STATUS
                   MOVE "Z00" TO WS-REASON
                   ADD 1 TO WS-CNT-DENY
               END-IF
           END-IF
           IF WS-BENEFIT > 0 AND AP-HH-SIZE NOT > 2
              AND WS-BENEFIT < 23
               MOVE 23 TO WS-BENEFIT
               MOVE "M23" TO WS-REASON
           END-IF
           IF WS-BENEFIT > 0
               MOVE "ELIGIBLE" TO WS-STATUS
               ADD 1 TO WS-CNT-ELIG
               ADD WS-BENEFIT TO WS-TOTAL-BEN
           END-IF.

       WRITE-DETAIL.
           MOVE AP-ID TO OUT-ID
           MOVE WS-STATUS TO OUT-STATUS
           MOVE WS-BENEFIT TO OUT-BENEFIT
           MOVE WS-REASON TO OUT-REASON
           WRITE REPORT-LINE FROM WS-OUT.

       WRITE-SUMMARY.
           MOVE "RECORDS READ" TO SUM-LABEL
           MOVE WS-CNT-READ TO SUM-VALUE
           WRITE REPORT-LINE FROM WS-SUM-LINE
           MOVE "ELIGIBLE" TO SUM-LABEL
           MOVE WS-CNT-ELIG TO SUM-VALUE
           WRITE REPORT-LINE FROM WS-SUM-LINE
           MOVE "DENIED" TO SUM-LABEL
           MOVE WS-CNT-DENY TO SUM-VALUE
           WRITE REPORT-LINE FROM WS-SUM-LINE
           MOVE "REJECTED" TO SUM-LABEL
           MOVE WS-CNT-REJ TO SUM-VALUE
           WRITE REPORT-LINE FROM WS-SUM-LINE
           MOVE "TOTAL BENEFITS" TO SUM-LABEL
           MOVE WS-TOTAL-BEN TO SUM-VALUE
           WRITE REPORT-LINE FROM WS-SUM-LINE.
